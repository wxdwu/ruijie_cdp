"""
小规模冒烟测试：用几百个假公司名跑一遍 generate_review_pairs 的分块逻辑，
验证「嵌入并行 + 按块落库检查点 + 已有对去重（可重入）」三条核心路径，
避免直接上 30w 全量才暴露问题。

设计要点：
- 用内存 SQLite（StaticPool 共享连接）替换真实 MySQL，避免依赖云库与 30w 数据。
- 并行嵌入：真实代码仅在配置了 Embedding API Key 时走 ThreadPoolExecutor；
  本测试强制进入该分支，但把 httpx.Client 改为「立即失败」，使每个 worker 快速回退到
  hash 兜底——从而离线、真实地跑通并行线程池 + 每批写缓存 + 进度聚合。
- 语义近似：hash 兜底无法区分「近义重名」，故临时替换为离线、确定性的「字符 bigram」嵌入，
  配合真实正阈值（EMBEDDING_SIMILARITY_THRESHOLD）让近义集群被召回、随机名被过滤，
  行为与生产一致且速度快。
- 检查点：把 DEDUP_WRITE_CHUNK 调小（如 30），使 120 个公司横跨多个块；用 ORM 会话
  after_commit 事件统计落库提交次数，证明「按块提交」而非末尾一次性提交。

运行：在 backend 目录下执行 `python scripts/smoke_test_dedup_chunks.py`
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path

# 将 backend 目录加入路径，保证 `import app` 可用
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np

from sqlalchemy import create_engine, event, text as satxt
from sqlalchemy.orm import sessionmaker, Session as ORMSession
from sqlalchemy.pool import StaticPool


# ─────────────────────────────────────────────────────────────────────────────
# 离线、确定性的「字符 bigram」嵌入（替换 hash 兜底，使近义重名有高余弦相似度）
# ─────────────────────────────────────────────────────────────────────────────
def _bigram_embedding(normalized: str, dim: int = 1536) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    if not normalized:
        return vec
    grams = [normalized[i : i + 2] for i in range(len(normalized) - 1)] or [normalized]
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def _make_fake_companies():
    """构造约 108 个假公司名 + 3 个高相似集群（各 4 个成员）。

    返回 (all_names, clusters)。集群成员被刻意散布在不同块（索引 0/30/60/90 等），
    以验证跨块落库检查点；集群内成员共享联系人电话，使证据分拉满、必然写入审核队列。
    """
    clusters = [
        # 集群 A：仅城市不同的「锐捷网络」系
        ["锐捷网络（北京）有限公司", "锐捷网络（上海）有限公司",
         "锐捷网络（广州）有限公司", "锐捷网络（深圳）有限公司"],
        # 集群 B：仅城市不同的「腾讯科技」系
        ["腾讯科技（深圳）有限公司", "腾讯科技（北京）有限公司",
         "腾讯科技（杭州）有限公司", "腾讯科技（成都）有限公司"],
        # 集群 C：仅城市不同的「阿里巴巴」系
        ["阿里巴巴（中国）有限公司", "阿里巴巴（杭州）有限公司",
         "阿里巴巴（上海）有限公司", "阿里巴巴（广州）有限公司"],
    ]
    # 填充名：前缀 × 后缀组合，互不相干，后缀多样避免 bigram 误重叠
    prefixes = ["星河", "云栖", "天工", "海纳", "数擎", "睿思", "百川", "磐石", "青松",
                "远见", "拓维", "凌云", "瀚海", "晨曦", "北辰", "景行", "九章", "大同",
                "明德", "至诚", "博远", "弘毅", "思源", "行知", "格物", "致知", "观澜",
                "听涛", "问道", "执中"]
    suffixes = ["工作室", "商行", "门市部", "研究院", "事务所", "中心", "集团", "联盟",
                "平台", "实验室", "咨询", "设计", "传媒", "物流", "餐饮", "健身", "教育",
                "科技", "网络", "农场"]
    fillers = []
    for i in range(108):
        fillers.append(f"{prefixes[i % len(prefixes)]}{suffixes[(i // len(prefixes)) % len(suffixes)]}")

    # 组装有序名单：把集群成员散布到固定间隔索引上，确保跨块
    names: list = list(fillers)  # 占位 108 位
    spread_slots = [0, 30, 60, 90, 5, 35, 65, 95, 10, 40, 70, 100]
    idx = 0
    for slot in spread_slots:
        names[slot] = clusters[idx // 4][idx % 4]
        idx += 1
    return names, clusters


def _create_schema(engine):
    with engine.begin() as conn:
        conn.execute(satxt("""
            CREATE TABLE dws_customer_360 (
                customer_name TEXT, id TEXT
            )
        """))
        conn.execute(satxt("""
            CREATE TABLE dws_contact_mapping (
                customer_name TEXT, mobile TEXT, email TEXT, contact_name TEXT
            )
        """))
        conn.execute(satxt("""
            CREATE TABLE dws_interaction_detail (
                customer_name TEXT, mobile TEXT, email TEXT, contact_name TEXT
            )
        """))
        conn.execute(satxt("""
            CREATE TABLE review_candidate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_type TEXT,
                candidate_a_id TEXT,
                candidate_a_name TEXT,
                candidate_b_id TEXT,
                candidate_b_name TEXT,
                match_score REAL,
                rule_score REAL,
                evidence_score REAL,
                llm_score REAL,
                evidence TEXT,
                status TEXT
            )
        """))


def run_smoke_test():
    from app.services.company_dedup import company_dedup  # 延迟导入，确保 sys.path 已就绪

    # ── 内存 SQLite（StaticPool 让所有连接共享同一库，模拟单一 MySQL 实例）──
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _create_schema(engine)
    SqlSession = sessionmaker(bind=engine, autoflush=False)

    # 注入假公司名（每个都带真实 id，确保审核队列 id 指向真实档案）
    fake_names, clusters = _make_fake_companies()
    with SqlSession() as s:
        for i, n in enumerate(fake_names):
            s.execute(
                satxt("INSERT INTO dws_customer_360 (customer_name, id) VALUES (:n, :id)"),
                {"n": n, "id": f"C{i:04d}"},
            )
        # 为每个近义集群注入「共享联系人」：集群内所有成员共用同一组电话，
        # 使证据分拉满（evidence_score=100），保证这些对必然写入 review_candidate，
        # 从而真实地走通「分块评分 -> 写入队列」路径（而非仅靠规则分卡阈值）。
        for ci, members in enumerate(clusters):
            shared_phones = [f"1390000{ci:02d}{k}" for k in range(5)]  # 每集群 5 个共享电话
            for m in members:
                for k, ph in enumerate(shared_phones):
                    s.execute(
                        satxt(
                            "INSERT INTO dws_contact_mapping "
                            "(customer_name, mobile, email, contact_name) "
                            "VALUES (:n, :ph, :em, :cn)"
                        ),
                        {"n": m, "ph": ph, "em": "", "cn": f"联系人{ci}-{k}"},
                    )
        s.commit()

    # ── 替换 company_dedup 的关键依赖 ──
    # 1) 会话：直接用内存 SQLite 的 sessionmaker
    company_dedup.SessionLocal = SqlSession
    # 2) 嵌入：离线字符 bigram（让近义重名有高相似度）
    company_dedup._hash_embedding = _bigram_embedding
    # 3) 缓存路径指向临时文件，避免污染仓库 data 目录
    tmp_cache = Path(tempfile.mkdtemp()) / "smoke_embeddings.db"
    company_dedup.get_cache_path = lambda: tmp_cache
    # 4) 分块大小调小，强制多个落库检查点
    company_dedup.DEDUP_WRITE_CHUNK = 30
    company_dedup.FAISS_K_NEAREST_NEIGHBORS = 200  # 覆盖全部近邻，避免漏召回
    company_dedup.EMBEDDING_SIMILARITY_THRESHOLD = 0.4  # 真实正阈值
    company_dedup.EMBEDDING_MAX_WORKERS = 4

    # 5) 强制进入「并行 API 分支」：设置假 key，并把 httpx.Client 改为立即失败，
    #    使每个 worker 快速回退 hash 兜底——离线跑通 ThreadPoolExecutor。
    from app.config import settings
    settings.EMBEDDING_API_KEY = "dummy-for-smoke"  # 仅用于触发并行分支

    import httpx
    commits = {"n": 0}
    parallel = {"used": False, "max_workers": None}

    class _FailClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a, **k):
            return False

        def post(self, *a, **k):
            # 模拟 embedding 端点不可达，触发 worker 内 hash 兜底
            raise httpx.ConnectError("simulated offline embedding endpoint")

    company_dedup.httpx.Client = _FailClient

    # 6) 用 spy 包装 ThreadPoolExecutor，记录是否使用及 max_workers
    import concurrent.futures as cf

    _RealTPE = cf.ThreadPoolExecutor

    class _SpyTPE(_RealTPE):
        def __init__(self, *args, **kwargs):
            parallel["used"] = True
            parallel["max_workers"] = kwargs.get("max_workers")
            super().__init__(*args, **kwargs)

    company_dedup.ThreadPoolExecutor = _SpyTPE

    # 7) after_commit 事件统计落库提交次数（检查点证明）
    def _on_commit(session):
        commits["n"] += 1

    event.listen(ORMSession, "after_commit", _on_commit)

    # ── 第一次运行：全量 ──
    print("\n=== 第一次运行（全量）===")
    stats1 = company_dedup.generate_review_pairs(incremental=False)

    with SqlSession() as s:
        rc_count1 = s.execute(satxt("SELECT COUNT(*) FROM review_candidate")).scalar()

    prog = company_dedup._dedup_progress
    print(f"  统计: {stats1}")
    print(f"  review_candidate 行数: {rc_count1}")
    print(f"  落库提交次数(after_commit): {commits['n']}")
    print(f"  并行线程池: used={parallel['used']}, max_workers={parallel['max_workers']}")
    print(f"  最终进度: {prog['progress']}%  step={prog['step']}")

    # ── 断言：分块检查点 + 并行 + 落库一致性 ──
    assert stats1["total_companies"] == len(fake_names), (
        f"total_companies 应为 {len(fake_names)}，实际 {stats1['total_companies']}"
    )
    assert stats1["new_pairs_found"] == rc_count1, (
        f"new_pairs_found({stats1['new_pairs_found']}) 应与 review_candidate 行数({rc_count1})一致"
    )
    assert stats1["new_pairs_found"] > 0, "应至少写入若干近义重名对"
    # 关键：多次提交证明「按块落库」而非末尾一次性提交
    assert commits["n"] >= 2, f"落库提交次数应 >=2（多块检查点），实际 {commits['n']}"
    # 关键：确实走了并行线程池
    assert parallel["used"] is True, "应进入并行 ThreadPoolExecutor 分支"
    assert parallel["max_workers"] == 4, (
        f"并行 worker 数应为 4，实际 {parallel['max_workers']}"
    )
    # 进度正确收尾（完成态记录在 details.step_name，顶层 step 保留最后一块的步骤名）
    assert prog["progress"] == 100, f"最终进度应为 100，实际 {prog['progress']}"
    assert prog["details"]["step_name"] == "完成", (
        f"最终步骤应为 完成，实际 {prog['details']['step_name']}"
    )

    # ── 第二次运行：验证「已有对去重 / 可重入」（检查点恢复完整性）──
    print("\n=== 第二次运行（重入，应去重为 0 新增）===")
    commits_before = commits["n"]
    stats2 = company_dedup.generate_review_pairs(incremental=False)
    with SqlSession() as s:
        rc_count2 = s.execute(satxt("SELECT COUNT(*) FROM review_candidate")).scalar()

    print(f"  统计: {stats2}")
    print(f"  review_candidate 行数: {rc_count2}")
    print(f"  本次新增提交（应为 0 新增行但仍有块提交）: {commits['n'] - commits_before}")

    assert stats2["new_pairs_found"] == 0, (
        f"第二次运行 new_pairs_found 应为 0（已有对去重），实际 {stats2['new_pairs_found']}"
    )
    assert rc_count2 == rc_count1, (
        f"第二次运行后 review_candidate 行数应不变（{rc_count1}），实际 {rc_count2}"
    )
    assert prog["progress"] == 100, "第二次运行最终进度也应为 100"
    assert prog["details"]["step_name"] == "完成", "第二次运行最终步骤应为 完成"

    print("\n[PASS] 冒烟测试全部通过：分块落库检查点、嵌入并行、可重入去重 均验证通过。")
    return True


if __name__ == "__main__":
    try:
        run_smoke_test()
    except AssertionError as e:
        print(f"\n[FAIL] 断言失败：{e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n[FAIL] 运行异常：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
