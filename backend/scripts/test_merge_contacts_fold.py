"""经过审核队列的端到端合并用例（内存 SQLite，无需云库）。

真实链路：审核队列里有候选 -> 审核员在审核界面点「通过」-> 审核通过后写入 company_merge_map
-> 客户管理界面查看，联系人 / 其他信息都按合并簇聚合。

场景：把「北京云图科技有限公司」与「云图科技（北京）有限公司」两个公司名合并。
两家本应同属一家公司：共享同一联系人「张伟」（手机号一致，证明是同一家、同一人），
又各自有独有联系人（A 李娜、B 王芳），以及不同的行业/负责人等「其他信息」。

验证点（逐条对应客户管理界面真实代码路径）：
1. 审核队列 review_candidate 存在 pending 候选项（即审核界面有「审核选项」）；
2. 真实调用 review_service.approve_review 审核通过 -> 返回 success、review_candidate.status=auto_merged；
3. company_merge_map 写入（含 canonical_id，验证此前 1054 修复）；
4. 客户列表折叠（对应 customer_service.get_customer_list 行255 的 NOT IN alias_name）：
   合并后别名公司不再单独出现在列表，标准名保留；
5. 客户详情联系人合并：点开任一公司详情，联系人 = 合并簇全部（重叠去重 + 独有补充，共 3 人）；
6. 客户详情「其他信息」合并：resolve_customer 返回合并簇成员 = {A, B}，
   且两家公司的 industry/region/owner 等属性都能在合并簇中聚合看到。

说明：生产端点 get_customer_detail / get_customer_contacts 的展示 SQL 含 MySQL 专有语法
（DATE_SUB / <=> / JSON_ARRAY），只能在 MySQL 跑；本用例在底层验证折叠机制（合并簇
member_ids/member_names + 同语义查询），真实 MySQL 上这些端点拿到合并簇后会返回同样合并后的结果。
"""

import os
import sys

import sqlalchemy
from sqlalchemy import create_engine, event, text as satxt
from sqlalchemy.pool import StaticPool

# 让脚本能 import 项目包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.company_dedup import company_merge, review_service  # noqa: E402


# ── 具体公司名与联系人（用例数据）──
NAME_A = "北京云图科技有限公司"      # 标准名（更短，decide_survivor 会选它）
NAME_B = "云图科技（北京）有限公司"  # 别名（被合并）
ID_A = "C0001"
ID_B = "C0002"
# A 公司联系人：张伟（与 B 共享）、李娜（A 独有）
CONTACTS_A = [
    ("张伟", "13800000001"),
    ("李娜", "13800000002"),
]
# B 公司联系人：张伟（与 A 共享，手机号一致）、王芳（B 独有）
CONTACTS_B = [
    ("张伟", "13800000001"),
    ("王芳", "13800000003"),
]


def _in_clause(prefix: str, values: list) -> tuple:
    """生成跨方言安全的 IN (...) 占位符与参数字典（SQLite 对 `IN (:tuple)` 单元素会绑定失败）。"""
    params = {f"{prefix}{i}": v for i, v in enumerate(values)}
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(values)))
    return f"IN ({placeholders})", params


def _make_engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _set_pragma(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=OFF")

    return eng


def _create_schema(eng):
    with eng.begin() as c:
        c.execute(satxt("""
            CREATE TABLE dws_customer_360 (
                id VARCHAR(64) PRIMARY KEY,
                customer_name VARCHAR(255),
                contact_count INT DEFAULT 0,
                mobile_count INT DEFAULT 0,
                purchase_stage VARCHAR(50),
                intent_level VARCHAR(50),
                industry VARCHAR(100),
                region VARCHAR(100),
                owner_name VARCHAR(100)
            )
        """))
        c.execute(satxt("""
            CREATE TABLE dws_contact_360 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id VARCHAR(64),
                contact_name VARCHAR(100),
                mobile VARCHAR(40)
            )
        """))
        c.execute(satxt("""
            CREATE TABLE company_merge_map (
                id BIGINT PRIMARY KEY,
                alias_name VARCHAR(255) NOT NULL,
                canonical_name VARCHAR(255) NOT NULL,
                canonical_id BIGINT,
                review_id BIGINT,
                merge_source VARCHAR(32) NOT NULL DEFAULT 'manual',
                merged_by VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (alias_name)
            )
        """))
        c.execute(satxt("""
            CREATE TABLE review_candidate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_type VARCHAR(50) NOT NULL DEFAULT 'company_merge',
                candidate_a_id VARCHAR(128) NOT NULL,
                candidate_a_name VARCHAR(255) NOT NULL,
                candidate_b_id VARCHAR(128) NOT NULL,
                candidate_b_name VARCHAR(255) NOT NULL,
                match_score DECIMAL(5,2),
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                evidence TEXT,
                reviewed_by VARCHAR(100),
                reviewed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))


def _seed(eng):
    with eng.begin() as c:
        c.execute(satxt(
            "INSERT INTO dws_customer_360 "
            "(id, customer_name, contact_count, mobile_count, "
            " purchase_stage, intent_level, industry, region, owner_name) "
            "VALUES (:id, :n, :cc, :mc, :ps, :il, :ind, :rg, :ow)"
        ), [
            {"id": ID_A, "n": NAME_A, "cc": len(CONTACTS_A), "mc": len(CONTACTS_A),
             "ps": "谈判中", "il": "高", "ind": "科技", "rg": "北京", "ow": "张三"},
            {"id": ID_B, "n": NAME_B, "cc": len(CONTACTS_B), "mc": len(CONTACTS_B),
             "ps": "意向", "il": "中", "ind": "软件", "rg": "北京", "ow": "李四"},
        ])
        rows = []
        for cid, contacts in ((ID_A, CONTACTS_A), (ID_B, CONTACTS_B)):
            for nm, mb in contacts:
                rows.append({"cid": cid, "nm": nm, "mb": mb})
        c.execute(satxt(
            "INSERT INTO dws_contact_360 (customer_id, contact_name, mobile) "
            "VALUES (:cid, :nm, :mb)"
        ), rows)
        # 审核队列：插入一条 pending 候选（模拟审核界面有「审核选项」）
        c.execute(satxt(
            "INSERT INTO review_candidate "
            "(review_type, candidate_a_id, candidate_a_name, "
            " candidate_b_id, candidate_b_name, match_score, status, evidence) "
            "VALUES (:rt, :aid, :an, :bid, :bn, :ms, 'pending', :ev)"
        ), {
            "rt": "company_merge", "aid": ID_A, "an": NAME_A,
            "bid": ID_B, "bn": NAME_B, "ms": 0.92, "ev": "{}",
        })


def _cluster_contacts(db, member_ids) -> set:
    """按合并簇 member_ids 查联系人（与 get_customer_contacts 主路径语义一致）。"""
    if not member_ids:
        return set()
    clause, params = _in_clause("cid", list(member_ids))
    rows = db.execute(
        satxt(f"SELECT contact_name, mobile FROM dws_contact_360 "
              f"WHERE customer_id {clause}"),
        params,
    ).mappings().all()
    return {(r["contact_name"], r["mobile"]) for r in rows}


def _list_after_merge(db) -> list:
    """客户列表的合并折叠（对应 customer_service.get_customer_list 行255 的过滤）。

    已被合并为别名的公司名不单独出现在列表中。
    """
    rows = db.execute(satxt(
        "SELECT customer_name FROM dws_customer_360 "
        "WHERE customer_name NOT IN (SELECT alias_name FROM company_merge_map)"
    )).mappings().all()
    return [r["customer_name"] for r in rows]


def _cluster_360(db, member_ids) -> list:
    """按合并簇 member_ids 聚合「其他信息」（与 get_customer_detail 按簇聚合的语义一致）。"""
    clause, params = _in_clause("mid", list(member_ids))
    rows = db.execute(satxt(
        f"SELECT customer_name, industry, region, owner_name "
        f"FROM dws_customer_360 WHERE id {clause}"
    ), params).mappings().all()
    return [dict(r) for r in rows]


def run() -> bool:
    # 测试已自建含 canonical_id 的 company_merge_map（SQLite 语法），跳过生产的 MySQL-only DDL
    company_merge.ensure_merge_map_table = lambda db: None
    # review_service._set_status 生产用 NOW()（MySQL 专有），在 SQLite 下换成 CURRENT_TIMESTAMP
    review_service._set_status = lambda db, item_id, status: db.execute(
        satxt(
            "UPDATE review_candidate "
            "SET status = :status, reviewed_by = 'system', reviewed_at = CURRENT_TIMESTAMP "
            "WHERE id = :id"
        ),
        {"status": status, "id": item_id},
    )

    eng = _make_engine()
    _create_schema(eng)
    _seed(eng)

    with eng.connect() as db:
        # ── 0. 审核队列里应有该 pending 候选（即审核界面有「审核选项」）──
        pending = db.execute(satxt(
            "SELECT id, candidate_a_name, candidate_b_name, status "
            "FROM review_candidate"
        )).mappings().fetchone()
        print(f"[审核队列] 待审核项: id={pending['id']} "
              f"{pending['candidate_a_name']} <-> {pending['candidate_b_name']} "
              f"status={pending['status']}")
        assert pending["status"] == "pending", "审核队列初始应为 pending"

        # 审核前：客户列表里 A、B 两个公司都独立出现
        before_list = _list_after_merge(db)
        print(f"[审核前] 客户列表公司: {before_list}")
        assert NAME_A in before_list and NAME_B in before_list, "审核前两家应独立出现"

        # ── 1. 审核员在审核界面点「通过」：真实调用 review_service.approve_review ──
        ret = review_service.approve_review(
            db, pending["id"], reviewed_by="审核员张三",
        )
        print(f"[审核] approve_review 返回: {ret}")
        assert ret["success"] is True, "审核应通过"
        assert ret["status"] == "auto_merged", "审核后状态应为 auto_merged"

        # ── 2. 审核队列状态已更新 ──
        st = db.execute(
            satxt("SELECT status FROM review_candidate WHERE id = :id"),
            {"id": pending["id"]},
        ).scalar()
        print(f"[审核] review_candidate.status = {st}")
        assert st == "auto_merged", "审核项状态应置为 auto_merged"

        # ── 3. company_merge_map 已写入（含 canonical_id）──
        row = db.execute(satxt(
            "SELECT alias_name, canonical_name, canonical_id "
            "FROM company_merge_map"
        )).mappings().fetchone()
        print(f"[合并映射] alias={row['alias_name']} canonical={row['canonical_name']} "
              f"canonical_id={row['canonical_id']}")
        assert row["alias_name"] == NAME_B, "别名应为 B"
        assert row["canonical_name"] == NAME_A, "标准名应为 A（更短）"
        assert row["canonical_id"] is not None, "canonical_id 应已写入（验证 1054 修复）"

        # ── 4. 客户管理 - 列表折叠：别名 B 不再出现，标准名 A 保留 ──
        after_list = _list_after_merge(db)
        print(f"[合并后] 客户列表公司: {after_list}")
        assert NAME_B not in after_list, "合并后别名公司不应再单独出现在客户列表"
        assert NAME_A in after_list, "合并后标准名公司应保留在客户列表"

        # ── 5. 客户管理 - 点开 A 详情：联系人合并（3 人，重叠去重 + 独有补充）──
        _, _, member_ids_a, member_names_a = company_merge.resolve_customer(db, ID_A)
        contacts_a = _cluster_contacts(db, member_ids_a)
        print(f"[合并后] 点开 {NAME_A} 详情，合并簇成员: {member_names_a}")
        print(f"[合并后] 点开 {NAME_A} 详情，联系人: {sorted(contacts_a)}")
        assert set(member_names_a) == {NAME_A, NAME_B}, \
            f"合并簇应含两个公司名，实际 {member_names_a}"
        expected = set(CONTACTS_A) | set(CONTACTS_B)
        assert contacts_a == expected, \
            f"联系人应聚合两家全部（重叠去重），差集={contacts_a ^ expected}"
        assert len(contacts_a) == 3, f"共享联系人应去重：预期 3 人，实际 {len(contacts_a)} 人"
        assert ("张伟", "13800000001") in contacts_a, "共享联系人张伟应保留且唯一"

        # ── 6. 客户管理 - 「其他信息」合并：合并簇能看到两家公司的 industry/region/owner ──
        info = _cluster_360(db, member_ids_a)
        print(f"[合并后] 合并簇其他信息（行业/区域/负责人）: "
              f"{[(r['customer_name'], r['industry'], r['region'], r['owner_name']) for r in info]}")
        names = {r["customer_name"] for r in info}
        assert names == {NAME_A, NAME_B}, f"合并簇应聚合两家公司的其他信息，实际 {names}"
        indus = {r["industry"] for r in info}
        assert indus == {"科技", "软件"}, "合并后应能看到两家公司各自的行业"

        # ── 7. 点开别名 B 详情，也应看到同一簇的联系人与其他信息 ──
        _, _, member_ids_b, _ = company_merge.resolve_customer(db, ID_B)
        contacts_b = _cluster_contacts(db, member_ids_b)
        info_b = _cluster_360(db, member_ids_b)
        print(f"[合并后] 点开 {NAME_B} 详情，联系人: {sorted(contacts_b)}")
        assert contacts_b == contacts_a, "别名公司详情也应聚合同一簇联系人"
        assert {r["customer_name"] for r in info_b} == names, \
            "别名公司详情也应聚合同一簇其他信息"

    print("\n[PASS] 经审核队列的端到端合并用例通过："
          "审核通过后，客户管理界面里别名公司被折叠、联系人与其他信息均按合并簇聚合。")
    return True


if __name__ == "__main__":
    try:
        run()
    except AssertionError as e:
        print(f"\n[FAIL] 断言失败：{e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n[FAIL] 运行异常：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
