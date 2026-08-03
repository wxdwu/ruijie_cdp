"""
公司合并持久化层（company_merge_map）。

设计要点
--------
合并只写映射表，不直接物理改写 DWS 四张聚合表：
- DWS（dws_customer_360 / dws_contact_mapping / dws_contact_360 / dws_interaction_detail）
  由 ETL 全量重建（TRUNCATE + 重载），任何物理改名/重挂都会在下次同步被 ods 源数据「还原」，
  因此物理合并无法持久。
- company_merge_map 是独立的持久层（ETL 不触碰它），记录「别名 -> 标准名」的合并关系，
  查询层按此折叠别名，从而实现「一次合并、永久生效、可退回」。
- 退回 = 删除映射行（DELETE），别名立即在查询层重新独立显示，无需重跑 ETL。

字段说明（相比备份设计的增强）
----------------------------
- alias_name / canonical_name：核心映射（唯一键 uk_alias 保证同一别名仅一条生效映射）。
- canonical_id：标准名在 dws_customer_360 的真实客户 id，便于联系人层按 id 折叠。
- review_id：来源 review_candidate.id（审计/按审核项退回）。
- merge_source：manual(人工审核) / auto(高置信自动) / branch(分支规则) / rebuild(存量回填)。
- merged_by：操作人（人工为工号，系统为 system）。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 建表
# ─────────────────────────────────────────────────────────────────────────────

def _dialect_name(db) -> str:
    """拿到当前会话/连接所用方言名（mysql/sqlite/...）。

    兼容 Session（有 .bind）与 Connection（自身即连接、无 .bind）两种传入。
    """
    bind = getattr(db, "bind", None)
    if bind is None:
        bind = db
    return getattr(getattr(bind, "dialect", None), "name", "mysql")


def _ensure_column(
    db: Session,
    table: str,
    column: str,
    definition: str,
) -> None:
    """幂等加列：老表（CREATE TABLE IF NOT EXISTS 不会补列）补齐后期新增字段。

    MySQL 不支持 `ADD COLUMN IF NOT EXISTS`，故先探测列是否存在再 ALTER。
    跨方言：MySQL 查 information_schema；SQLite 用 PRAGMA table_info（无 information_schema）。
    """
    dialect = _dialect_name(db)
    if dialect == "sqlite":
        cols = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
        exists = any(str(row[1]) == column for row in cols)
    else:
        exists = db.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = :tbl AND column_name = :col"
            ),
            {"tbl": table, "col": column},
        ).first()
    if not exists:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        db.commit()


def ensure_merge_map_table(db: Session) -> None:
    """确保 company_merge_map 表存在（幂等；CREATE IF NOT EXISTS）。

    并对已存在的老表做列迁移：CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，
    故后期新增的 canonical_id 需单独 ALTER 补齐，否则 record_merge 的 INSERT 会报
    1054 Unknown column 'canonical_id'。
    """
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS company_merge_map (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            alias_name VARCHAR(255) NOT NULL
                COMMENT '被合并的别名公司名',
            canonical_name VARCHAR(255) NOT NULL
                COMMENT '合并后的标准公司名（幸存者 / 总部主体）',
            canonical_id BIGINT NULL
                COMMENT '标准公司名在 dws_customer_360 的真实客户 id',
            review_id BIGINT NULL
                COMMENT '来源 review_candidate.id',
            merge_source VARCHAR(32) NOT NULL DEFAULT 'manual'
                COMMENT '合并来源: manual/auto/branch/rebuild',
            merged_by VARCHAR(100) NULL
                COMMENT '操作人（人工为工号，系统为 system）',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_alias (alias_name),
            KEY idx_canonical (canonical_name)
        )
    """))
    db.commit()
    # 老表补齐：CREATE TABLE IF NOT EXISTS 不会给已存在的老表补列。
    # 真实库里 company_merge_map 可能是早期 schema（缺 canonical_id / review_id /
    # merge_source / merged_by / created_at），故逐列幂等 ALTER，避免 upsert 报 1054。
    _ensure_column(
        db, "company_merge_map", "canonical_id",
        "BIGINT NULL COMMENT '标准公司名在 dws_customer_360 的真实客户 id'",
    )
    _ensure_column(
        db, "company_merge_map", "alias_id",
        "BIGINT NULL COMMENT 'merged alias company real id in dws_customer_360'",
    )
    _ensure_column(
        db, "company_merge_map", "review_id",
        "BIGINT NULL COMMENT '来源 review_candidate.id'",
    )
    _ensure_column(
        db, "company_merge_map", "merge_source",
        "VARCHAR(32) NOT NULL DEFAULT 'manual' "
        "COMMENT '合并来源: manual/auto/branch/rebuild'",
    )
    _ensure_column(
        db, "company_merge_map", "merged_by",
        "VARCHAR(100) NULL COMMENT '操作人（人工为工号，系统为 system）'",
    )
    _ensure_column(
        db, "company_merge_map", "created_at",
        "DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '合并时间'",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 映射图加载与传递闭包解析
# ─────────────────────────────────────────────────────────────────────────────

def _load_map(db: Session) -> Dict[str, str]:
    """加载全部 {alias_name: canonical_name}。"""
    rows = db.execute(
        text("SELECT alias_name, canonical_name FROM company_merge_map")
    ).mappings().all()
    return {r["alias_name"]: r["canonical_name"] for r in rows}


def _build_roots(alias_map: Dict[str, str]) -> Dict[str, str]:
    """把别名->标准名的映射做并查集归并，返回每个节点到其连通分量根（标准名）的映射。

    根取连通分量内「作为标准名出现过」的节点；若无标准名节点（理论上不应发生），
    退化为字典序最小者。
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        # 路径压缩
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for alias, canonical in alias_map.items():
        ra, rc = find(alias), find(canonical)
        if ra != rc:
            parent[ra] = rc

    roots = {node: find(node) for node in parent}
    return roots


def _resolve(name: str, alias_map: Dict[str, str], roots: Dict[str, str]) -> str:
    """解析单个名称到其标准名（传递闭包）。"""
    if name in roots:
        return roots[name]
    if name in alias_map:
        return roots.get(alias_map[name], alias_map[name])
    return name


def _index(db: Session) -> Tuple[Dict[str, str], Dict[str, str]]:
    alias_map = _load_map(db)
    roots = _build_roots(alias_map)
    return alias_map, roots


def _resolve_name(db: Session, name: str) -> str:
    alias_map, roots = _index(db)
    return _resolve(name, alias_map, roots)


def get_member_names(db: Session, name: str) -> List[str]:
    """返回 name 所属合并簇的全部成员公司名（含标准名本身）。"""
    alias_map, roots = _index(db)
    root = _resolve(name, alias_map, roots)
    members = [n for n, r in roots.items() if r == root]
    if root not in members:
        members.append(root)
    seen: set = set()
    out: List[str] = []
    for m in members:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _in_clause(prefix: str, values: Sequence[str]) -> Tuple[str, Dict[str, str]]:
    """生成跨方言安全的 IN (...) 占位符与参数字典。

    避免 `IN (:tuple)` 在 SQLite 上对单元素序列绑定失败（MySQL 能展开、SQLite 不能）。
    返回 (占位符片段如 "IN (:p0, :p1)", {p0:.., p1:..})，调用方拼接到 WHERE 后。
    """
    params = {f"{prefix}{i}": v for i, v in enumerate(values)}
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(values)))
    return f"IN ({placeholders})", params


def resolve_customer(
    db: Session, customer_id: Any
) -> Tuple[Optional[str], Optional[str], List[Any], List[str]]:
    """按客户 id 解析合并上下文。

    返回 (canonical_id, canonical_name, member_ids, member_names)：
    - canonical_id：标准公司名在 dws_customer_360 的 id（联系人层按 id 折叠用）。
    - canonical_name：标准公司名。
    - member_ids：合并簇内所有成员在 dws_customer_360 的 id 列表。
    - member_names：合并簇内所有成员的公司名列表。
    未合并时返回 (customer_id, 自身名, [customer_id], [自身名])。
    """
    row = db.execute(
        text("SELECT id, customer_name FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).mappings().fetchone()
    if not row:
        return None, None, [], []

    self_name = row["customer_name"]
    member_names = get_member_names(db, self_name)
    in_clause, in_params = _in_clause("mid", member_names)
    id_rows = db.execute(
        text(
            f"SELECT id, customer_name FROM dws_customer_360 "
            f"WHERE customer_name {in_clause}"
        ),
        in_params,
    ).mappings().all()
    id_by_name = {r["customer_name"]: r["id"] for r in id_rows}
    member_ids = [id_by_name[n] for n in member_names if n in id_by_name]

    canonical_name = _resolve_name(db, self_name)
    canonical_id = id_by_name.get(canonical_name)
    return canonical_id, canonical_name, member_ids, member_names


# ─────────────────────────────────────────────────────────────────────────────
# 合并链追溯（供详情页展示）
# ─────────────────────────────────────────────────────────────────────────────

# 合并链最大展示长度：超过后折叠为「...」，避免超长链撑爆 UI（仅截断展示，不影响数据）。
MERGE_CHAIN_MAX_LEN = 8


def get_merge_chain(db: Session, customer_id: Any) -> Dict[str, Any]:
    """返回客户在合并映射中的可追溯信息，供前端详情页紧凑展示。

    返回结构：
    - is_canonical：当前客户是否为「最终合并者」（簇内根节点）。
    - canonical_id / canonical_name：最终合并者 id 与名称。
    - merged_count：若 is_canonical，合并了几家公司（簇成员数 - 1）。
    - merged_members：若 is_canonical，被合并成员名列表（不含 canonical 自身）。
    - merge_chain：从当前公司逐步合并到最终合并者的路径（含当前与最终），
      如 [当前, 中间1, ..., 最终]；带环检测，超 MERGE_CHAIN_MAX_LEN 折叠。

    未合并（自身即根、且簇仅自身）时返回空结构，前端据此不渲染合并信息。
    """
    row = db.execute(
        text("SELECT id, customer_name FROM dws_customer_360 WHERE id = :cid"),
        {"cid": customer_id},
    ).mappings().fetchone()
    if not row:
        return _empty_chain()

    self_name = row["customer_name"]
    self_id = row["id"]

    alias_map = _load_map(db)
    roots = _build_roots(alias_map)
    canonical_name = _resolve(self_name, alias_map, roots)
    # 最终合并者 id：优先从映射表取 canonical_id（最准），否则按名回查 dws。
    canonical_id = _fetch_c360_id(db, canonical_name)

    member_names = get_member_names(db, self_name)

    is_canonical = self_name == canonical_name
    merged_members = [n for n in member_names if n != canonical_name] if is_canonical else []
    merged_count = len(merged_members) if is_canonical else 0

    # 被合并成员带 id，供前端点击跳转（批量按名查 dws，避免 N+1）
    merged_member_infos: List[Dict[str, Any]] = []
    if merged_members:
        in_clause, in_params = _in_clause("mm", merged_members)
        rows = db.execute(
            text(
                f"SELECT id, customer_name FROM dws_customer_360 "
                f"WHERE customer_name {in_clause}"
            ),
            in_params,
        ).mappings().all()
        id_by_name = {r["customer_name"]: r["id"] for r in rows}
        merged_member_infos = [
            {"name": n, "id": id_by_name.get(n)} for n in merged_members
        ]

    # 逐步合并链：从当前名沿 alias->canonical 向上溯源到根，带环检测与长度上限。
    chain = _trace_chain(self_name, alias_map, canonical_name)

    return {
        "is_canonical": is_canonical,
        "canonical_id": canonical_id,
        "canonical_name": canonical_name,
        "self_id": self_id,
        "self_name": self_name,
        "merged_count": merged_count,
        "merged_members": merged_members,
        "merged_member_infos": merged_member_infos,
        "merge_chain": chain,
    }


def _trace_chain(self_name: str, alias_map: Dict[str, str], canonical_name: str) -> List[Dict[str, Any]]:
    """从 self_name 沿映射溯源到 canonical_name，得到逐步合并路径。

    返回形如 [{"name": 当前, "id": ...}, {"name": 中间, "id": ...}, {"name": 最终, "id": ...}]。
    环检测：若遍历中遇到已访问节点，立即终止并截断，避免死循环。
    超长截断：路径超过 MERGE_CHAIN_MAX_LEN 时，保留首尾并在中间插入折叠标记。
    """
    db = None  # 延迟取连接，仅在需要 id 时查询
    visited: set = set()
    raw_path: List[str] = []
    cur = self_name
    while cur and cur != canonical_name and cur not in visited:
        visited.add(cur)
        raw_path.append(cur)
        nxt = alias_map.get(cur)
        if nxt is None:
            break
        cur = nxt
    if cur == canonical_name:
        raw_path.append(canonical_name)

    # 环或异常截断保护
    if len(raw_path) > MERGE_CHAIN_MAX_LEN:
        head = raw_path[: MERGE_CHAIN_MAX_LEN - 2]
        tail = raw_path[-1]
        folded = head + ["__FOLD__"] + [tail]
    else:
        folded = raw_path

    # 解析每个节点的 dws id（按名批量查询，避免 N+1）
    names = [n for n in folded if n != "__FOLD__"]
    id_by_name: Dict[str, Optional[int]] = {}
    if names:
        from app.database import SessionLocal
        with SessionLocal() as s:
            in_clause2, in_params2 = _in_clause("cid", names)
            r2 = s.execute(
                text(
                    f"SELECT id, customer_name FROM dws_customer_360 "
                    f"WHERE customer_name {in_clause2}"
                ),
                in_params2,
            ).mappings().all()
            id_by_name = {r["customer_name"]: r["id"] for r in r2}

    chain: List[Dict[str, Any]] = []
    for n in folded:
        if n == "__FOLD__":
            chain.append({"name": "...", "id": None, "folded": True})
        else:
            chain.append({"name": n, "id": id_by_name.get(n), "folded": False})
    return chain


def _empty_chain() -> Dict[str, Any]:
    """无合并信息时返回的空结构。"""
    return {
        "is_canonical": False,
        "canonical_id": None,
        "canonical_name": None,
        "self_id": None,
        "self_name": None,
        "merged_count": 0,
        "merged_members": [],
        "merged_member_infos": [],
        "merge_chain": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 判定幸存者（标准名）
# ─────────────────────────────────────────────────────────────────────────────

def decide_survivor(name_a: str, name_b: str, db: Session) -> str:
    """在两个公司名间挑选「幸存者 / 标准名」。

    优先级：联系人数量多者 -> 手机号数量多者 -> 名称更短者（更可能是总部主体）。
    """
    in_clause, in_params = _in_clause("sid", (name_a, name_b))
    rows = db.execute(
        text(
            "SELECT customer_name, "
            "COALESCE(contact_count, 0) AS contact_count, "
            "COALESCE(mobile_count, 0) AS mobile_count "
            f"FROM dws_customer_360 WHERE customer_name {in_clause}"
        ),
        in_params,
    ).mappings().all()
    metrics = {
        r["customer_name"]: (r["contact_count"], r["mobile_count"]) for r in rows
    }
    ma = metrics.get(name_a, (0, 0))
    mb = metrics.get(name_b, (0, 0))
    if (ma[0], ma[1]) != (mb[0], mb[1]):
        return name_a if (ma[0], ma[1]) > (mb[0], mb[1]) else name_b
    return name_a if len(name_a) <= len(name_b) else name_b


def _fetch_c360_id(db: Session, name: str) -> Optional[int]:
    row = db.execute(
        text("SELECT id FROM dws_customer_360 WHERE customer_name = :n LIMIT 1"),
        {"n": name},
    ).fetchone()
    return row[0] if row else None


def _branch_canonical_from_evidence(evidence: Any) -> Optional[str]:
    """从审核证据 JSON 中提取分支机构合并指定的标准名（若有）。"""
    if not evidence:
        return None
    try:
        data = json.loads(evidence) if isinstance(evidence, str) else evidence
    except Exception:
        return None
    if isinstance(data, dict):
        return data.get("branch_canonical")
    return None


def _coerce_id(value):
    """Coerce candidate_a_id / candidate_b_id (VARCHAR, may be None / 'default_id') to int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s or s.lower() == "default_id":
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _batch_fetch_c360_metrics(db, names):
    """Batch fetch (contact_count, mobile_count) by name for survivor decision."""
    result = {}
    if not names:
        return result
    in_clause, params = _in_clause("m", list(names))
    rows = db.execute(
        text(
            "SELECT customer_name, "
            "COALESCE(contact_count, 0) AS cc, "
            "COALESCE(mobile_count, 0) AS mc "
            f"FROM dws_customer_360 WHERE customer_name {in_clause}"
        ),
        params,
    ).mappings().all()
    for r in rows:
        result[r["customer_name"]] = (r["cc"], r["mc"])
    return result


def _batch_fetch_c360_ids(db, names):
    """Batch fetch dws_customer_360.id by name for alias_id / canonical_id backfill."""
    result = {}
    if not names:
        return result
    in_clause, params = _in_clause("i", list(names))
    rows = db.execute(
        text(
            "SELECT id, customer_name "
            f"FROM dws_customer_360 WHERE customer_name {in_clause}"
        ),
        params,
    ).mappings().all()
    for r in rows:
        result[r["customer_name"]] = r["id"]
    return result


def _decide_survivor_metrics(name_a, name_b, metrics):
    """Pick survivor from pre-fetched metrics (same rule as decide_survivor, no per-row query)."""
    ma = metrics.get(name_a, (0, 0))
    mb = metrics.get(name_b, (0, 0))
    if (ma[0], ma[1]) != (mb[0], mb[1]):
        return name_a if (ma[0], ma[1]) > (mb[0], mb[1]) else name_b
    return name_a if len(name_a) <= len(name_b) else name_b


def _decide_canonical(a_name, b_name, id_by_name, metrics):
    """Choose canonical name for merge rebuild, guaranteeing it exists in dws_customer_360.

    Using only contact/mobile metrics cannot distinguish "present in dws_customer_360 with
    zero contacts" from "absent from dws" (both are (0,0)); a tie falls back to the shorter /
    ordered name, which may pick a name absent from dws_customer_360 as canonical, yielding a
    NULL canonical_id and making the detail page 404. So "exists in dws_customer_360" is the
    top priority:
    1) only one side present -> take the present side (canonical must have a real id);
    2) both present -> keep _decide_survivor_metrics (more contacts/mobiles, then shorter);
    3) neither present -> return None (caller skips; nothing to fold).
    """
    a_in = a_name in id_by_name
    b_in = b_name in id_by_name
    if a_in and not b_in:
        return a_name
    if b_in and not a_in:
        return b_name
    if not a_in and not b_in:
        return None
    return _decide_survivor_metrics(a_name, b_name, metrics)


# ─────────────────────────────────────────────────────────────────────────────
# 写入 / 退回
# ─────────────────────────────────────────────────────────────────────────────

def record_merge(
    db: Session,
    name_a: str,
    name_b: str,
    *,
    review_id: Optional[int] = None,
    merged_by: Optional[str] = None,
    merge_source: str = "manual",
    force_canonical: Optional[str] = None,
) -> Dict[str, Any]:
    """记录一次合并：把两个公司名归并到同一标准名，写入 company_merge_map。

    支持传递性：若任一名称已属某个合并簇，则整簇归并到新标准名。
    ON DUPLICATE KEY UPDATE 保证幂等（同一别名仅保留一条生效映射）。
    """
    ensure_merge_map_table(db)

    alias_map, roots = _index(db)
    existing_a = _resolve(name_a, alias_map, roots)
    existing_b = _resolve(name_b, alias_map, roots)
    # 已在同一簇（且非本次待合并的原始名之一）-> 无需重复合并
    if existing_a == existing_b and existing_a not in (name_a, name_b):
        return {"merged": False, "canonical_name": existing_a, "reason": "already_merged"}

    canonical = force_canonical or decide_survivor(name_a, name_b, db)

    # 收集本次要重新映射到 canonical 的所有别名（含两侧簇的成员）
    need_relink: set = set()
    for nm in (name_a, name_b):
        r = _resolve(nm, alias_map, roots)
        for alias, root in roots.items():
            if root == r and alias != canonical:
                need_relink.add(alias)
        if nm != canonical:
            need_relink.add(nm)
    need_relink.discard(canonical)

    canonical_id = _fetch_c360_id(db, canonical)
    # ensure canonical exists in dws_customer_360: if canonical absent but alias present, swap;
    # otherwise (both absent) skip this merge to avoid a NULL canonical_id.
    if canonical_id is None:
        alias_side = name_b if canonical == name_a else name_a
        alias_side_id = _fetch_c360_id(db, alias_side)
        if alias_side_id is not None:
            canonical, canonical_id = alias_side, alias_side_id
        else:
            logger.warning(
                "merge skipped (both names absent from dws_customer_360): %s / %s", name_a, name_b
            )
            db.commit()
            return {"merged": False, "canonical_name": None, "reason": "no_c360_record"}
    alias_id_map = _batch_fetch_c360_ids(db, sorted(need_relink))

    # upsert 跨方言：MySQL 用 ON DUPLICATE KEY UPDATE；SQLite 用 ON CONFLICT(...)。
    dialect = _dialect_name(db)
    for alias in sorted(need_relink):
        params = {
            "alias": alias,
            "canonical": canonical,
            "canonical_id": canonical_id,
            "alias_id": alias_id_map.get(alias),
            "review_id": review_id,
            "merge_source": merge_source,
            "merged_by": merged_by,
        }
        if dialect == "sqlite":
            db.execute(
                text("""
                    INSERT INTO company_merge_map
                        (alias_name, canonical_name, canonical_id, alias_id,
                         review_id, merge_source, merged_by)
                    VALUES
                        (:alias, :canonical, :canonical_id, :alias_id,
                         :review_id, :merge_source, :merged_by)
                    ON CONFLICT(alias_name) DO UPDATE SET
                        canonical_name = excluded.canonical_name,
                        canonical_id   = excluded.canonical_id,
                        alias_id       = excluded.alias_id,
                        review_id      = excluded.review_id,
                        merge_source   = excluded.merge_source,
                        merged_by      = excluded.merged_by
                """),
                params,
            )
        else:
            db.execute(
                text("""
                    INSERT INTO company_merge_map
                        (alias_name, canonical_name, canonical_id, alias_id,
                         review_id, merge_source, merged_by)
                    VALUES
                        (:alias, :canonical, :canonical_id, :alias_id,
                         :review_id, :merge_source, :merged_by)
                    ON DUPLICATE KEY UPDATE
                        canonical_name = VALUES(canonical_name),
                        canonical_id   = VALUES(canonical_id),
                        alias_id       = VALUES(alias_id),
                        review_id      = VALUES(review_id),
                        merge_source   = VALUES(merge_source),
                        merged_by      = VALUES(merged_by),
                        created_at     = NOW()
                """),
                params,
            )
    db.commit()
    return {
        "merged": True,
        "canonical_name": canonical,
        "canonical_id": canonical_id,
        "relinked": sorted(need_relink),
    }


def rollback_merge_by_alias(db: Session, alias_name: str) -> bool:
    """按别名退回一次合并（删除映射行）。返回是否有行被删除。"""
    ensure_merge_map_table(db)
    result = db.execute(
        text("DELETE FROM company_merge_map WHERE alias_name = :alias"),
        {"alias": alias_name},
    )
    db.commit()
    return result.rowcount > 0


def rollback_merge_by_review_id(db: Session, review_id: int) -> int:
    """按审核项 id 退回其产生的合并（可能多条别名）。返回删除行数。"""
    ensure_merge_map_table(db)
    result = db.execute(
        text("DELETE FROM company_merge_map WHERE review_id = :rid"),
        {"rid": review_id},
    )
    db.commit()
    return result.rowcount


def list_merges(
    db: Session,
    *,
    canonical_name: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> Dict[str, Any]:
    """列出当前生效的合并映射（供管理/审计界面）。"""
    ensure_merge_map_table(db)
    where_parts = ["1=1"]
    params: Dict[str, Any] = {}
    if canonical_name:
        where_parts.append("canonical_name LIKE :cn")
        params["cn"] = f"%{canonical_name}%"
    where_sql = " AND ".join(where_parts)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM company_merge_map WHERE {where_sql}"),
        params,
    ).scalar() or 0
    rows = db.execute(
        text(
            f"SELECT * FROM company_merge_map WHERE {where_sql} "
            f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ),
        {**params, "lim": size, "off": (max(1, page) - 1) * size},
    ).mappings().all()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": size,
    }


def sync_auto_merged_to_map(db: Optional[Session] = None) -> int:
    """把 review_candidate 中已 auto_merged 的合并关系同步进映射表（幂等）。

    该函数是「自动合并」真正落库的入口：手动合并在 approve 时直接 record_merge，
    不经过此函数。因此只要此处被可靠调用，自动合并的两个公司才会真正被折叠。

    幂等：已存在映射会被 record_merge 识别为 already_merged 而跳过。
    逐行容错：单条写入失败仅记日志、不影响其余候选对，避免一条脏数据导致整批
    自动合并丢失（历史上「标记了 auto_merged 却没真正合并」缺口的根因之一）。
    db 为 None 时自行开/关会话，便于从定时任务或修复端点独立调用。
    """
    # 读取候选对：用独立会话（不持有写锁），避免与逐行写入共用一个长事务。
    read_db = db if db is not None else SessionLocal()
    try:
        ensure_merge_map_table(read_db)
        rows = read_db.execute(
            text(
                "SELECT id, candidate_a_name, candidate_b_name, evidence "
                "FROM review_candidate WHERE status = 'auto_merged'"
            )
        ).mappings().all()
    finally:
        if db is None:
            read_db.close()

    # 逐行用独立会话落库：同一 canonical 的多个别名并发 upsert 易触发 MySQL 死锁
    # (1213)，独立会话 + 死锁重试可隔离锁、自愈；不再用单一长事务累积锁。
    count = 0
    for r in rows:
        if _sync_one_auto_merge(r):
            count += 1
    return count


def _sync_one_auto_merge(r: Dict[str, Any]) -> bool:
    """同步单条 auto_merged 候选对进映射表；独立会话 + 死锁重试。

    返回该候选对是否成功写入映射。非死锁类异常直接跳过（不影响其余候选对）。
    """
    max_retry = 3
    for attempt in range(1, max_retry + 1):
        s = SessionLocal()
        try:
            force = _branch_canonical_from_evidence(r.get("evidence"))
            rec = record_merge(
                s,
                r["candidate_a_name"],
                r["candidate_b_name"],
                review_id=r["id"],
                merged_by="system",
                merge_source="auto",
                force_canonical=force,
            )
            return bool(rec.get("merged"))
        except Exception as _e:
            err_str = str(_e)
            is_deadlock = "1213" in err_str or "Deadlock" in err_str
            logger.warning(
                "自动合并同步单条失败（重试 %s/%s，review_id=%s，%s<->%s）: %s",
                attempt, max_retry, r.get("id"), r.get("candidate_a_name"),
                r.get("candidate_b_name"), _e,
            )
            try:
                s.rollback()
            except Exception:
                pass
            if not is_deadlock or attempt >= max_retry:
                return False
            # 退避后重试，错开对同一 canonical 的并发 upsert 争用
            time.sleep(0.2 * attempt)
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False

# MARKER_TEST_PYWRITE

def rebuild_merge_map_from_review(db=None, *, clear_existing=True, chunk=2000):
    """Rebuild company_merge_map (with alias_id) entirely from review_candidate.

    review_candidate (status auto_merged / merged) is the single source of truth for
    merges: each pair already has a decided canonical/alias, and its candidate_a_id /
    candidate_b_id are the real dws_customer_360 ids. Hence company_merge_map (including
    the new alias_id) can be fully reconstructed from it without other tables.

    Logic:
    - load all candidate pairs with status IN ('auto_merged','merged');
    - canonical = branch_canonical from evidence if present, else survivor by
      (contact_count, mobile_count) then shorter name;
    - alias_id / canonical_id prefer the pair's *_id (most accurate, already dws ids),
      fall back to name lookup;
    - dedup by alias_name (last write wins); clear=True truncates then refills to stay
      strictly consistent with review_candidate;
    - the query layer (_build_roots) already chains transitive merges via union-find at
      read time, so writing per-pair alias->canonical here is semantically equivalent
      without an expensive full-cluster relink.

    Returns a stats dict for the API / logging.
    """
    read_db = db if db is not None else SessionLocal()
    try:
        ensure_merge_map_table(read_db)
        before_count = read_db.execute(
            text("SELECT COUNT(*) FROM company_merge_map")
        ).scalar() or 0
        rows = read_db.execute(text(
            "SELECT id, candidate_a_id, candidate_a_name, "
            "candidate_b_id, candidate_b_name, status, evidence "
            "FROM review_candidate WHERE status IN ('auto_merged', 'merged')"
        )).mappings().all()
    finally:
        if db is None:
            read_db.close()

    total = len(rows)
    auto_merged = sum(1 for r in rows if r["status"] == "auto_merged")
    manual_merged = total - auto_merged
    names = set()
    for r in rows:
        names.add(r["candidate_a_name"])
        names.add(r["candidate_b_name"])
    name_list = list(names)

    aux_db = read_db if db is not None else SessionLocal()
    try:
        metrics = _batch_fetch_c360_metrics(aux_db, name_list)
        id_by_name = _batch_fetch_c360_ids(aux_db, name_list)
    finally:
        if db is None:
            aux_db.close()

    merged_rows = {}
    skipped = 0
    for r in rows:
        a_name, b_name = r["candidate_a_name"], r["candidate_b_name"]
        force = _branch_canonical_from_evidence(r.get("evidence"))
        # if forced canonical is absent from dws_customer_360 (removed/never existed), drop force
        if force is not None and force not in id_by_name:
            force = None
        canonical = force if force is not None else _decide_canonical(
            a_name, b_name, id_by_name, metrics
        )
        if canonical is None:
            skipped += 1
            continue
        alias = b_name if canonical == a_name else a_name
        if alias == canonical:
            skipped += 1
            continue
        # canonical_id / alias_id always taken from CURRENT dws_customer_360 ids:
        # avoids NULL canonical_id, and also fixes stale ids left by full ETL id churn.
        canonical_id = id_by_name.get(canonical)
        alias_id = id_by_name.get(alias)
        if canonical_id is None:
            skipped += 1
            continue
        merged_rows[alias] = {
            "alias_name": alias,
            "canonical_name": canonical,
            "canonical_id": canonical_id,
            "alias_id": alias_id,
            "review_id": r["id"],
            "merge_source": "auto" if r["status"] == "auto_merged" else "manual",
            "merged_by": "system" if r["status"] == "auto_merged" else "rebuild",
        }

    distinct_aliases = len(merged_rows)
    write_db = SessionLocal()
    try:
        ensure_merge_map_table(write_db)
        if clear_existing:
            write_db.execute(text("DELETE FROM company_merge_map"))
            write_db.commit()
        items = list(merged_rows.values())
        insert_sql = text("""
            INSERT INTO company_merge_map
                (alias_name, canonical_name, canonical_id, alias_id,
                 review_id, merge_source, merged_by)
            VALUES
                (:alias_name, :canonical_name, :canonical_id, :alias_id,
                 :review_id, :merge_source, :merged_by)
            ON DUPLICATE KEY UPDATE
                canonical_name = VALUES(canonical_name),
                canonical_id   = VALUES(canonical_id),
                alias_id       = VALUES(alias_id),
                review_id      = VALUES(review_id),
                merge_source   = VALUES(merge_source),
                merged_by      = VALUES(merged_by),
                created_at     = NOW()
        """)
        for i in range(0, len(items), chunk):
            write_db.execute(insert_sql, items[i:i + chunk])
        write_db.commit()
        after_count = write_db.execute(
            text("SELECT COUNT(*) FROM company_merge_map")
        ).scalar() or 0
    finally:
        write_db.close()

    logger.info(
        "rebuild company_merge_map from review_candidate done: "
        "review=%s (auto=%s, manual=%s), aliases=%s, skipped=%s, "
        "clear=%s, rows %s -> %s",
        total, auto_merged, manual_merged, distinct_aliases, skipped,
        clear_existing, before_count, after_count,
    )
    return {
        "total_review_rows": total,
        "auto_merged": auto_merged,
        "manual_merged": manual_merged,
        "distinct_aliases": distinct_aliases,
        "skipped": skipped,
        "before_count": before_count,
        "after_count": after_count,
        "clear_existing": clear_existing,
    }

# R1785298235.1143098
