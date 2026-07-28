"""审核面板「候选公司画像」富集回归测试（内存 SQLite，无需云库）。

守护目标：
1) 修复前 _enrich_with_company_details 在公司名精确匹配不到 dws_customer_360 时，
   会用 LIKE %名% + 相似度兜底把「另一家相似公司」的整份画像错配给当前候选，
   导致审核面板展示的基本信息与公司名对不上。
2) 联系人数量 / 近 30 天互动 / 总互动 必须从真实聚合表（dws_contact_360 /
   dws_interaction_detail）计算，而非直接读 dws_customer_360 中可能失真的聚合字段
   （如 360.contact_count=0 但真实有 2 个联系人）。
3) 「数据表」来源标签仅展示公司真实存在数据的表：公司不在 dws_contact_mapping
   时该标签不展示，但 dws_customer_360（有 id）/ dws_interaction_detail（有互动）保留。

覆盖用例：
A. 候选名精确存在于 360 -> 取自身画像，联系人/互动从真实表计算；
B. 候选名不存在且无别名映射 -> detail=None（不展示、不错配）；
C. 候选名是已合并公司的别名 -> 解析到标准名并取标准名画像（非第三家）；
D. 反例守护：相似但不同公司，断言不返回那家公司的画像；
E. 复现用户场景：公司 360.contact_count=0 失真，但 dws_contact_360 真实有 2 个联系人、
   不在 dws_contact_mapping -> 联系人显示 2、近 30 天互动为计算值、dws_contact_mapping 标签被过滤；
F. 来源表标签：公司在 dws_contact_mapping 有记录时保留该标签，无记录时剔除。
"""

import os
import sys

import sqlalchemy
from sqlalchemy import create_engine, event, text as satxt
from sqlalchemy.pool import StaticPool

# 让脚本能 import 项目包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.company_dedup import company_merge, review_service  # noqa: E402


# ── 用例公司名 ──
NAME_A = "XX科技有限公司"            # 候选 A：当前 360 中真实存在
NAME_B = "XX科技集团有限公司"        # 与 A 名称相似但为不同公司（反例守护对象）
NAME_C = "云图科技（北京）有限公司"  # 已作为别名被合并到标准名 NAME_CANON
NAME_CANON = "北京云图科技有限公司"   # 标准名：当前 360 中真实存在
NAME_MISSING = "不存在的公司某某某"   # 360 中无此公司、也无别名映射
# 用户场景：360.contact_count 失真为 0，但真实有 2 个联系人，且不在 dws_contact_mapping
NAME_D = "安徽省委党校（安徽行政学院）"
NAME_E1 = "合肥市人民政府（主）"    # 合并簇主公司
NAME_E2 = "合肥市人民政府（别名）"  # 合并簇别名（与 E1 合并）


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
                industry VARCHAR(100),
                region VARCHAR(100),
                owner_name VARCHAR(100),
                intent_level VARCHAR(50),
                purchase_stage VARCHAR(50),
                active_opp_count INT DEFAULT 0,
                interaction_count_30d INT DEFAULT 0,
                interaction_count_total INT DEFAULT 0,
                last_interaction_time VARCHAR(32),
                source_tables TEXT,
                data_coverage TEXT,
                is_existing_customer TINYINT DEFAULT 0
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
            CREATE TABLE dws_contact_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name VARCHAR(255),
                mobile VARCHAR(40)
            )
        """))
        c.execute(satxt("""
            CREATE TABLE dws_interaction_detail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name VARCHAR(255),
                contact_name VARCHAR(255),
                behavior_type VARCHAR(64),
                event_time VARCHAR(32)
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


def _seed_contacts(eng, c360_id, n):
    rows = [
        {"cid": c360_id, "nm": f"联系人{i}", "mb": f"138{n}{i:04d}"}
        for i in range(1, n + 1)
    ]
    with eng.begin() as c:
        c.execute(satxt(
            "INSERT INTO dws_contact_360 (customer_id, contact_name, mobile) "
            "VALUES (:cid, :nm, :mb)"
        ), rows)


def _seed_contact_mapping(eng, name, mobiles):
    rows = [{"nm": name, "mb": mb} for mb in mobiles]
    with eng.begin() as c:
        c.execute(satxt(
            "INSERT INTO dws_contact_mapping (customer_name, mobile) VALUES (:nm, :mb)"
        ), rows)


def _seed_interactions(eng, name, events):
    """events: 元素为 (contact_name, behavior_type, event_time)。"""
    rows = [{"nm": name, "cn": cn, "bt": bt, "t": t} for (cn, bt, t) in events]
    with eng.begin() as c:
        c.execute(satxt(
            "INSERT INTO dws_interaction_detail "
            "(customer_name, contact_name, behavior_type, event_time) "
            "VALUES (:nm, :cn, :bt, :t)"
        ), rows)


def _seed(eng):
    with eng.begin() as c:
        # 360 中真实存在的三家公司，各自画像不同（用 industry/contact_count 区分）
        c.execute(satxt(
            "INSERT INTO dws_customer_360 "
            "(id, customer_name, contact_count, industry, region, owner_name) "
            "VALUES (:id, :n, :cc, :ind, :rg, :ow)"
        ), [
            {"id": "C0001", "n": NAME_A, "cc": 5, "ind": "软件", "rg": "深圳", "ow": "甲"},
            {"id": "C0002", "n": NAME_B, "cc": 12, "ind": "硬件", "rg": "上海", "ow": "乙"},
            {"id": "C0003", "n": NAME_CANON, "cc": 8, "ind": "科技", "rg": "北京", "ow": "丙"},
            # 用户场景公司：360.contact_count 失真为 0（与真实 2 个联系人不符）
            {"id": "C0004", "n": NAME_D, "cc": 0, "ind": "教育", "rg": "合肥", "ow": "丁"},
            # 合并簇去重用例：E1 为主公司，E2 是其别名（两公司合并后应为一个簇）
            {"id": "C0005", "n": NAME_E1, "cc": 1, "ind": "政府", "rg": "合肥", "ow": "戊"},
            {"id": "C0006", "n": NAME_E2, "cc": 1, "ind": "政府", "rg": "合肥", "ow": "戊"},
        ])
        # 合并映射：NAME_C 是 NAME_CANON 的别名（既往合并）
        c.execute(satxt(
            "INSERT INTO company_merge_map "
            "(id, alias_name, canonical_name, canonical_id, merge_source) "
            "VALUES (1, :al, :ca, :cid, 'manual')"
        ), {"al": NAME_C, "ca": NAME_CANON, "cid": "C0003"})
        # 合并映射：NAME_E2 是 NAME_E1 的别名（用于合并簇去重用例）
        c.execute(satxt(
            "INSERT INTO company_merge_map "
            "(id, alias_name, canonical_name, canonical_id, merge_source) "
            "VALUES (2, :al, :ca, :cid, 'manual')"
        ), {"al": NAME_E2, "ca": NAME_E1, "cid": "C0005"})

    # 真实联系人数据（权威来源 dws_contact_360），与 360.contact_count 一致或修正
    _seed_contacts(eng, "C0001", 5)
    _seed_contacts(eng, "C0002", 12)
    _seed_contacts(eng, "C0003", 8)
    _seed_contacts(eng, "C0004", 2)  # 用户场景：真实 2 个联系人，尽管 360 写的是 0
    # 合并簇：E1 与 E2 各有一条「张三 / 1380000001」——名字+手机号相同，应合并为 1 个联系人
    _seed_contacts(eng, "C0005", 1)
    _seed_contacts(eng, "C0006", 1)

    # dws_contact_mapping：A/B/CANON 有记录（标签应保留），NAME_D 故意不写入
    _seed_contact_mapping(eng, NAME_A, ["138100001", "138100002"])
    _seed_contact_mapping(eng, NAME_B, ["138200001"])
    _seed_contact_mapping(eng, NAME_CANON, ["138300001"])

    # 互动明细：NAME_D 有 1 条近 30 天 + 1 条较早（远 > 30 天）-> 近 30 天=1、总计=2
    _seed_interactions(eng, NAME_D, [
        ("联系人甲", "浏览", "2026-07-25 10:00:00"),
        ("联系人甲", "浏览", "2026-01-01 10:00:00"),
    ])
    # 合并簇互动：E1/E2 各有一条完全相同的互动（张三/浏览/2026-07-20 10:00:00），
    # 应去重为 1 条；另 E2 有一条独有的（李四/拨打/2026-07-15 09:00:00）。
    _seed_interactions(eng, NAME_E1, [
        ("张三", "浏览", "2026-07-20 10:00:00"),
    ])
    _seed_interactions(eng, NAME_E2, [
        ("张三", "浏览", "2026-07-20 10:00:00"),
        ("李四", "拨打", "2026-07-15 09:00:00"),
    ])


def _enrich(db, a_name, b_name=None, sources_a=None, sources_b=None):
    """构造一条审核项并走真实富集逻辑，返回 (item) 供按需取字段。"""
    item = {
        "candidate_a_name": a_name,
        "candidate_b_name": b_name or "",
        "sources_a": sources_a,
        "sources_b": sources_b,
    }
    items = review_service._enrich_with_company_details([item], db)
    return items[0]


def run() -> bool:
    # 跳过生产的 MySQL-only DDL；确保 company_merge_map 表存在供 _resolve_name 读取
    company_merge.ensure_merge_map_table = lambda db: None

    eng = _make_engine()
    _create_schema(eng)
    _seed(eng)

    with eng.connect() as db:
        # ── 用例 A：精确命中 -> 取自身正确画像，联系人/互动从真实表计算 ──
        item_a = _enrich(db, NAME_A)
        detail_a = item_a["candidate_a_detail"]
        assert detail_a is not None, "候选名精确存在于 360 时应取回画像"
        assert detail_a["customer_name"] == NAME_A, "画像公司名必须等于候选名"
        assert detail_a["industry"] == "软件", "应取到 A 自身的行业"
        # 联系人从 dws_contact_360 计算（5 条）
        assert detail_a["contact_count"] == 5, "联系人应从 dws_contact_360 计算为 5"
        print(f"[用例A] 精确命中 {NAME_A} -> 行业={detail_a['industry']} "
              f"联系人={detail_a['contact_count']}（自身画像正确）")

        # ── 用例 B：不存在且无别名 -> detail=None（不展示、不错配）──
        item_b = _enrich(db, NAME_MISSING)
        detail_missing = item_b["candidate_a_detail"]
        assert detail_missing is None, "360 中不存在且无别名时不应借用任何公司画像"
        print(f"[用例B] {NAME_MISSING} 不在 360 且无别名 -> detail=None（不展示虚假画像）")

        # ── 用例 C：已合并别名 -> 解析到标准名并取标准名画像（非第三家）──
        item_c = _enrich(db, NAME_C)
        detail_c = item_c["candidate_a_detail"]
        assert detail_c is not None, "已合并别名应解析到标准名并取回画像"
        assert detail_c["customer_name"] == NAME_CANON, "别名应解析到标准名而非其它公司"
        assert detail_c["industry"] == "科技", "应取到标准名自身的行业"
        # 标准名 CANON 真实有 8 个联系人
        assert detail_c["contact_count"] == 8, "应取到标准名从 dws_contact_360 计算的 8 个联系人"
        print(f"[用例C] 别名 {NAME_C} -> 解析到 {detail_c['customer_name']} "
              f"行业={detail_c['industry']} 联系人={detail_c['contact_count']}（同簇，非第三家）")

        # ── 用例 D（反例守护）：相似但不同公司 -> 绝不返回那家公司的画像 ──
        item_d = _enrich(db, NAME_A)
        detail_d = item_d["candidate_a_detail"]
        assert detail_d["customer_name"] == NAME_A, "候选 A 的画像公司名必须为自身"
        assert detail_d["industry"] != "硬件", f"候选 A 不应被错配为 {NAME_B} 的硬件行业"
        assert detail_d["contact_count"] != 12, f"候选 A 不应被错配为 {NAME_B} 的联系人数量"

        item_b2 = _enrich(db, NAME_B)
        detail_b = item_b2["candidate_a_detail"]
        assert detail_b["customer_name"] == NAME_B, "候选 B 的画像公司名必须为自身"
        assert detail_b["industry"] == "硬件", "候选 B 应取到自身硬件行业"
        print(f"[用例D] 反例守护：{NAME_A} 与 {NAME_B} 相似但为不同公司，"
              f"各自取到自身画像（行业 {detail_a['industry']}/{detail_b['industry']}），"
              f"未发生跨公司错配")

        # ── 用例 E：复现用户场景（360.contact_count 失真为 0，真实 2 个联系人）──
        item_d4 = _enrich(
            db, NAME_D,
            sources_a=[
                {"table": "dws_customer_360", "record_id": "C0004"},
                {"table": "dws_contact_mapping", "record_id": None},
                {"table": "dws_interaction_detail", "record_id": None},
            ],
        )
        detail_d4 = item_d4["candidate_a_detail"]
        assert detail_d4 is not None, "NAME_D 在 360 中应取回画像"
        # 关键修复点：联系人数必须从 dws_contact_360 计算为 2，而不是 360 失真的 0
        assert detail_d4["contact_count"] == 2, (
            f"联系人应从 dws_contact_360 计算为 2，实际 {detail_d4['contact_count']}（修复前读 360 的 0）"
        )
        # 近 30 天互动 / 总互动从 dws_interaction_detail 计算
        assert detail_d4["interaction_count_30d"] == 1, (
            "近 30 天互动应从 dws_interaction_detail 计算为 1"
        )
        assert detail_d4["interaction_count_total"] == 2, (
            "总互动应从 dws_interaction_detail 计算为 2"
        )
        # 来源标签：NAME_D 不在 dws_contact_mapping -> 该标签被过滤掉；
        #          在 dws_customer_360（有 id）/ dws_interaction_detail（有互动）-> 保留
        kept_tables = [s["table"] for s in (item_d4["sources_a"] or [])]
        assert "dws_contact_mapping" not in kept_tables, (
            "公司不在 dws_contact_mapping 时不应展示该来源标签"
        )
        assert "dws_customer_360" in kept_tables, "dws_customer_360 应保留（有 id）"
        assert "dws_interaction_detail" in kept_tables, (
            "dws_interaction_detail 应保留（有互动明细）"
        )
        print(f"[用例E] 用户场景 {NAME_D} -> 联系人={detail_d4['contact_count']} "
              f"(修复前误显 0)、近30天互动={detail_d4['interaction_count_30d']}、"
              f"总互动={detail_d4['interaction_count_total']}；"
              f"来源标签={kept_tables}（已过滤 dws_contact_mapping）")

        # ── 用例 F：公司在 dws_contact_mapping 有记录时保留该标签 ──
        item_f = _enrich(
            db, NAME_A,
            sources_a=[
                {"table": "dws_customer_360", "record_id": "C0001"},
                {"table": "dws_contact_mapping", "record_id": None},
            ],
        )
        kept_f = [s["table"] for s in (item_f["sources_a"] or [])]
        assert "dws_contact_mapping" in kept_f, (
            "公司在 dws_contact_mapping 有记录时应保留该来源标签"
        )
        print(f"[用例F] {NAME_A} 在 dws_contact_mapping 有记录 -> 来源标签保留 {kept_f}")

        # ── 用例 G：合并簇去重（同一人被两个合并公司重复、同一互动被重复）──
        item_g = _enrich(db, NAME_E1)
        detail_g = item_g["candidate_a_detail"]
        g_cc = detail_g["contact_count"]
        g_i30 = detail_g["interaction_count_30d"]
        g_it = detail_g["interaction_count_total"]
        # E1/E2 各有一条「张三/1380000001」-> 姓名+手机号相同，应合并为 1 个联系人
        assert g_cc == 1, (
            f"合并簇联系人去重应为 1（姓名+手机号相同合并），实际 {g_cc}"
        )
        # 两条完全相同的互动（张三/浏览/2026-07-20 10:00:00）去重为 1 + 李四独有 1 = 2
        assert g_it == 2, f"合并簇互动去重总计应为 2，实际 {g_it}"
        # 两条均落在近 30 天内
        assert g_i30 == 2, f"合并簇近30天互动去重应为 2，实际 {g_i30}"
        print(f"[用例G] 合并簇 {NAME_E1} -> 联系人={g_cc}（姓名+手机号去重）、"
              f"近30天互动={g_i30}、总互动={g_it}（姓名/行为/时间去重）")

    print("\n[PASS] 审核面板「候选公司画像」富集回归测试通过：")
    print("  - 精确命中自身画像、缺失置空、别名解析同簇、相似不同公司不错配；")
    print("  - 联系人/近30天互动/总互动均从真实聚合表计算（修复 360 失真导致的 0）；")
    print("  - 来源表标签仅展示公司真实存在数据的表（dws_contact_mapping 缺失则过滤）；")
    print("  - 合并簇维度：联系人按(姓名+手机号)去重、互动按(姓名,行为类型,事件时间)去重。")
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
