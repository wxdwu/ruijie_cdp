"""
Company Name Deduplication Service using Embeddings and Rule-based Scoring.

Provides functionality to:
- Fetch company names from multiple sources
- Normalize and clean company names
- Compute embeddings for semantic similarity
- Find potential duplicate pairs
- Score matches using multiple methods
- Generate review queue items
- Auto-merge high-confidence matches
"""

from __future__ import annotations

import time
from datetime import datetime

import hashlib
import json
import logging
import httpx
import os
import pickle
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, cast, Dict, Iterator, List, Optional, Tuple

import numpy as np
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.ai.llm_client import LLMClient
from app.services.common.company_name_clean import clean_company_symbols

logger = logging.getLogger(__name__)

# =============================================================================
# BUSINESS CONFIGURATION — 去重审核队列业务配置（统一管理，便于调整）
#
# 配置概览：
#   A. 步骤进度 — 去重流水线上各阶段在用户端进度条中占的百分比区间
#   B. 阈值     — 控制候选对筛选、自动合并/人工审核分流的关键门槛
#   C. 评分权重 — 综合评分公式中各子项的贡献比例
#   D. 数据源   — 参与去重的数据表、优先级、证据评分查询表
#   E. LLM     — 大模型调用相关配置
#
# 注意：修改任一配置后需要重启后端服务才能生效。
# =============================================================================

# ──────────────────────────────────────────────────────────────────────────────
# A. 去重阶段划分与进度模型（唯一配置源）
# ──────────────────────────────────────────────────────────────────────────────
# 旧模型：单一 0-100 标量被各阶段反复覆盖，分块循环里「证据评分」每块的起点都会把
# 进度从 80%+ 拉回 45%（即用户看到的“快 100% 又退回 30%”的诡异回退）。
# 新模型（单调阶段化）：
#   - 每个阶段拥有固定的百分比区间（权重），全局进度 = 阶段起始% + 权重% × 阶段内完成度；
#   - 全局进度取 max(历史值)，【永远单调不减】，彻底杜绝回退；
#   - 阶段内部分块工作时只更新「块级子进度」(details)，不再回写全局进度；
#   - 附带 elapsed_seconds / eta_seconds / phase_index / phase_name，供前端做步骤条与预计剩余。
#
# ★ DEDUP_PHASES 是阶段权重的【唯一配置源】，修改只需改此列表（权重之和须为 100）。

DEDUP_PHASES: List[Tuple[str, int]] = [
    ("获取公司名称", 8),       # 0: 0%   → 8%
    ("计算嵌入向量", 22),      # 1: 8%   → 30%（含并行线程）
    ("查找相似对", 14),        # 2: 30%  → 44%
    ("评分与写入队列", 55),    # 3: 44%  → 99%（分块：块内证据评分占前半段、写库占后半段）
    ("完成", 1),               # 4: 99%  → 100%
]
assert sum(w for _, w in DEDUP_PHASES) == 100, "DEDUP_PHASES 权重之和必须为 100"

# 由权重推导每个阶段的 [起始%, 结束%] 区间
_DEDUP_PHASE_RANGE: List[Tuple[float, float]] = []
_cum = 0.0
for _name, _w in DEDUP_PHASES:
    _DEDUP_PHASE_RANGE.append((_cum, _cum + _w))
    _cum += _w
DEDUP_PHASE_NAMES: List[str] = [name for name, _ in DEDUP_PHASES]

# 向后兼容：保留旧常量名（语义变为各阶段区间端点），防止其它潜在引用意外失效
DEDUP_PROGRESS_STEPS = [
    (name, start, end) for (name, _), (start, end) in zip(DEDUP_PHASES, _DEDUP_PHASE_RANGE)
]
STEP_GET_COMPANIES_PROGRESS = _DEDUP_PHASE_RANGE[0][0]
STEP_EMBEDDING_PROGRESS_START = _DEDUP_PHASE_RANGE[1][0]
STEP_EMBEDDING_PROGRESS_RANGE = _DEDUP_PHASE_RANGE[1][1] - _DEDUP_PHASE_RANGE[1][0]
STEP_SIMILAR_PAIRS_PROGRESS_START = _DEDUP_PHASE_RANGE[2][0]
STEP_SIMILAR_PAIRS_PROGRESS_RANGE = _DEDUP_PHASE_RANGE[2][1] - _DEDUP_PHASE_RANGE[2][0]
STEP_EVIDENCE_PROGRESS_START = _DEDUP_PHASE_RANGE[3][0]
STEP_EVIDENCE_PROGRESS_RANGE = 0  # 证据评分并入阶段3前半段，不再单独占区间
STEP_CHECK_EXISTING_PROGRESS = _DEDUP_PHASE_RANGE[3][0]
STEP_SCORE_WRITE_PROGRESS_START = _DEDUP_PHASE_RANGE[3][0]
STEP_SCORE_WRITE_PROGRESS_RANGE = _DEDUP_PHASE_RANGE[3][1] - _DEDUP_PHASE_RANGE[3][0]
STEP_COMPLETE_PROGRESS = _DEDUP_PHASE_RANGE[4][1]

# ──────────────────────────────────────────────────────────────────────────────
# B. 阈值配置
# ──────────────────────────────────────────────────────────────────────────────
# 这些阈值直接决定去重流水线"筛选多少候选对"以及"自动合并/人工审核/丢弃"的分流。

# 嵌入向量余弦相似度最低阈值，范围 (0, 1]
# 含义：两条公司名的 embedding 向量余弦相似度必须 ≥ 此值，才会被纳入候选 pair 列表。
# 影响：
#   - 调高 → 候选对更少、更精准，但可能漏掉一些近似但不完全相同的公司名。
#   - 调低 → 候选对更多、召回率更高，但计算量和噪音也会增大。
#   - 当前 0.70 是一个相对平衡的值，能召回大部分"同义词/缩写/别称"的情况。
EMBEDDING_SIMILARITY_THRESHOLD = 0.70

# 公司名称最小长度（字符数，含中英文）
# 含义：公司名长度 < 此值的记录直接丢弃，不参与去重。
# 作用：排除如"北京""上海""广州"等极短的地名/碎片，这类名称信息量不足，
#       容易与包含相同子串的正常公司名产生误匹配。
# 注意：DEDUP_TEST_MODE_MAX_COMPANIES 的限制在长度过滤之后生效。
MIN_COMPANY_NAME_LENGTH = 4

# FAISS 搜索每个向量的最近邻数量（k 近邻参数）
# 含义：对每个公司名向量，从索引中查找余弦相似度最高的前 k 个邻居。
# 影响：k 越大，候选对数量指数级增长（因为每对都在结果里出现两次）。
#       实际生成 candidate pairs 时还会用 EMBEDDING_SIMILARITY_THRESHOLD 做二次过滤。
FAISS_K_NEAREST_NEIGHBORS = 50

# 自动合并阈值，范围 [0, 100]
# 含义：综合评分（rule + evidence + LLM 加权和）> 此值时，系统自动将两条公司记录
#       合并为一条，无需人工介入。review_queue.status 设为 "auto_merged"。
# 影响：
#   - 调高 → 更保守，只有极度相似的 pair 才自动合并，减少误合并风险。
#   - 调低 → 更激进，更多 pair 被自动合并，减少人工审核压力但风险更高。
AUTO_MERGE_THRESHOLD = 85

# 人工审核阈值（下界），范围 [0, AUTO_MERGE_THRESHOLD]
# 含义：综合评分在 (NEED_REVIEW_THRESHOLD, AUTO_MERGE_THRESHOLD] 区间内的 pair
#       会进入人工审核队列，等待运营人员在 ReviewQueue 页面上做"合并/忽略"决策。
#       评分 ≤ NEED_REVIEW_THRESHOLD 的 pair 直接丢弃（视为不相关）。
# 影响：
#   - 调高 → 减少人工审核工作量，但可能漏掉一些需要人工判断的模糊 case。
#   - 调低 → 增加召回，更多模糊 pair 送人工确认，但审核压力增大。
NEED_REVIEW_THRESHOLD = 35

# 高置信度自动合并阈值，范围 [0, 100]
# 含义：供 auto_merge_high_confidence() 函数使用，对已经处于 need_review 状态的 pair
#       再次扫描，如果当前综合评分 > 此值则升级为自动合并（适用于数据更新后评分提升的场景）。
#       通常比 AUTO_MERGE_THRESHOLD 更高，代表"二次确认"级别的高置信度。
# 注意：此阈值作用于复审阶段，与首次写入队列时使用的 AUTO_MERGE_THRESHOLD 相互独立。
HIGH_CONFIDENCE_MERGE_THRESHOLD = 90.0

# ──────────────────────────────────────────────────────────────────────────────
# C. 评分权重配置 — 综合评分 = rule_score × Wr + evidence_score × We + LLM_score × Wl
# ──────────────────────────────────────────────────────────────────────────────
# 所有分值都已归一化到 [0, 100] 区间，三个权重之和等于 1.0，确保最终得分可解释。

# 最终综合评分 — 规则分权重
# 含义：规则引擎（编辑距离、子串包含、前缀后缀、token/Jaccard 等字符串算法）在最终
#       决策中占 35%。规则分擅长发现字形/字符层面的相似性，速度快、可解释性强。
FINAL_RULE_WEIGHT = 0.35

# 最终综合评分 — 证据分权重
# 含义：证据评分（两条公司记录共享的电话/邮箱联系人数量换算得分）在最终决策中占 40%。
#       证据分反映了业务层面的关联度——共享的联系人越多，两家公司越可能是同一家。
#       当前权重最高，体现了"以业务数据为锚点"的策略。
FINAL_EVIDENCE_WEIGHT = 0.40

# 最终综合评分 — LLM 分权重
# 含义：大模型语义判断分在最终决策中占 25%。LLM 能识别规则引擎难以处理的语义等价
#       （如"字节跳动"与"ByteDance"、简称/全称替换等），但受限于调用延迟和成本。
FINAL_LLM_WEIGHT = 0.25

# ── 规则评分各因子权重（规则分 = 各因子得分 × 各自权重后累加） ──────────────────
# 规则评分内部由 5 个独立的字符串相似度指标加权求和得到，每个因子的得分范围均为 [0,100]。
# 所有权重之和 > 1 是正常的（各因子之间并非互斥，而是相互补充），最终 scores 列表元素的
# 加权和就是规则分原始值。

# 编辑距离（Levenshtein）相似度权重
# 算法：两公司名标准化后计算 Levenshtein 编辑距离，转换为 0~100 的相似度分数。
# 擅长：发现拼写差异（如 "腾讯科技" vs "腾迅科技" 的"讯/迅"一字之差）。
RULE_LEVENSHTEIN_WEIGHT = 0.30

# 子串包含权重
# 算法：如果公司名 A 是 B 的子串（或反之），按长度比给分。
# 擅长：发现"含与不含"后缀的关系（如 "华为" vs "华为技术有限公司"）。
RULE_SUBSTRING_WEIGHT = 0.25

# 公共前缀权重
# 算法：从首字符开始找连续相同的子串长度，按比例给分。
# 擅长：发现同一集团/品牌下子公司（如 "阿里巴巴(中国)" vs "阿里巴巴(杭州)"）。
RULE_PREFIX_WEIGHT = 0.10

# 公共后缀权重
# 算法：从尾字符倒着找连续相同的子串长度，按比例给分。
# 擅长：发现以相同后缀结尾的公司（如 "XX科技有限公司" vs "YY科技有限公司"）。
RULE_SUFFIX_WEIGHT = 0.10

# Token（词语）重叠度权重
# 算法：按空格/分词器拆分后，计算 Jaccard 系数（交集大小/并集大小）。
# 擅长：发现词序不同但关键词重合度高的情况（如 "中国移动通信" vs "移动通信中国"）。
RULE_TOKEN_WEIGHT = 0.25

# 字符级 Jaccard 权重
# 算法：将公司名字符集合做 Jaccard 计算（不关心顺序，只看字符集合重叠）。
# 擅长：发现简繁体、中英文混杂等情况下的字符重叠度。
RULE_JACCARD_WEIGHT = 0.20

# ──────────────────────────────────────────────────────────────────────────────
# 证据评分乘数（每个共享联系人贡献的分数）
# ──────────────────────────────────────────────────────────────────────────────
# 含义：在所有 ODS 表中查到两条公司名共享的电话或邮箱数 total_shared，
#       证据分 = min(100, total_shared × EVIDENCE_SCORE_MULTIPLIER)。
#       例如：共享 3 个联系人 → 3×20 = 60 分；共享 5 个及以上 → 封顶 100 分。
# 影响：
#   - 调高 → 少量共享联系人即可获得高证据分，容易触发自动合并。
#   - 调低 → 需要更多共享联系人才能获得相同的证据分，更保守。
EVIDENCE_SCORE_MULTIPLIER = 20.0

# ──────────────────────────────────────────────────────────────────────────────
# LLM 不可用时回落权重
# ──────────────────────────────────────────────────────────────────────────────
# 场景：当 LLM API key 未配置、调用超时/失败、或返回结果无法解析时，
#       系统回退到只用规则分和证据分估算一个替代 LLM 分。
#       回落 LLM 分 = (rule_score × LLM_FALLBACK_RULE_WEIGHT
#                       + evidence_score × LLM_FALLBACK_EVIDENCE_WEIGHT) / 100
#              （结果归一化到 [0,1]，后续会再乘 FINAL_LLM_WEIGHT）
# 含义：这两个权重决定了在 LLM 缺席时，规则分和证据分各自贡献多少来补齐 LLM 的缺口。
#       当前 0.5/0.5 表示等权分配。
LLM_FALLBACK_RULE_WEIGHT = 0.5
LLM_FALLBACK_EVIDENCE_WEIGHT = 0.5

# ──────────────────────────────────────────────────────────────────────────────
# D. 数据源配置
# ──────────────────────────────────────────────────────────────────────────────

# 数据源优先级（数值越高越可信，用于选择主公司记录）
# 含义：当一个公司的数据出现在多个数据源中时，优先以哪个源的记录作为主记录
#       （主记录决定最终展示的公司名、统一社会信用代码等关键字段）。
#       优先级越高，越可能被选为"代表该公司的记录"。
SOURCE_PRIORITY = {
    'crm': 6,                        # CRM 系统 — 最可信，销售直接维护
    'lead': 5,                       # 线索系统 — 市场渠道过来的公司
    'tianrun_session': 4,            # 天润会话 — 客服/电销触达数据
    'zhique_behavior': 3,            # 知鹊行为 — 网站/小程序行为埋点
    'linkflow': 2,                   # LinkFlow — 营销自动化
    'email_click': 1,                # 邮件点击 — 可信度最低的匿名行为
}

# 去重涉及的数据源表名（全量表扫描阶段读取这些 DWS 聚合表获取所有公司名）。
# 仅依赖 dws 四张聚合表，不再直接读 ods：
# - dws_customer_360：客户360宽表（主体，含真实客户 id）
# - dws_contact_mapping：联系人映射聚合表（含各 ods 联系人来源的公司名）
# - dws_interaction_detail：互动明细聚合表（含各 ods 互动来源的公司名）
# dws_contact_360 仅含 customer_id 无公司名列，不参与公司名发现。
DEDUP_DATA_SOURCES = [
    "dws_customer_360",
    "dws_contact_mapping",
    "dws_interaction_detail",
]

# 证据评分查询的 DWS 聚合表定义
# 含义：计算证据分时，在这些 dws 聚合表中搜索两条公司名各自的联系信息（电话/邮箱），
#       统计双方共享的联系人数量作为"两家公司有关联"的证据。不再直接读 ods。
# 字段说明：
#   - table:          表名
#   - company_field:  表中表示公司名的字段
#   - phone_field:    表中电话号码字段（用于匹配）
#   - email_field:    表中邮箱字段（用于匹配）；为 None 表示该表无邮箱列（如 dws_interaction_detail）
EVIDENCE_TABLES = [
    {"table": "dws_contact_mapping", "company_field": "customer_name", "phone_field": "mobile", "email_field": "email"},
    {"table": "dws_interaction_detail", "company_field": "customer_name", "phone_field": "mobile", "email_field": None},
]

# ──────────────────────────────────────────────────────────────────────────────
# E. LLM 配置
# ──────────────────────────────────────────────────────────────────────────────

# 大模型名称（用于调用 LLM judge 判断两条公司名是否代表同一家公司）
# 当前使用 DeepSeek Chat（api.deepseek.com），兼容 OpenAI 协议。
# 也可替换为 deepseek-reasoner 或其他兼容 OpenAI 协议的模型。


# =============================================================================
# END CONFIGURATION
# =============================================================================

# Global dedup progress tracking
_dedup_progress = {
    "status": "idle",
    "step": "",
    "progress": 0,
    "total": 0,
    "results": None,
    "details": None,  # 详细进度信息: {"step_name","completed","total","message", 块级信息...}
    # ── 单调阶段化进度模型新增字段 ──
    "started_at": None,
    "phase_index": 0,           # 当前阶段下标（DEDUP_PHASES）
    "phase_name": "",           # 当前阶段名
    "phase_progress": 0.0,      # 当前阶段内部完成度 %
    "overall_progress": 0.0,    # 全局进度 %（单调不减）
    "eta_seconds": None,        # 预计剩余秒数
    "elapsed_seconds": None,    # 已耗时（秒）
    "throughput": None,         # 吞吐（阶段3：公司/秒）
    "phases": DEDUP_PHASE_NAMES,  # 阶段名列表，供前端步骤条渲染
}
_dedup_lock = threading.Lock()


def _set_phase_progress(phase_index: int, local_fraction: float,
                        extra: Optional[Dict[str, Any]] = None) -> None:
    """统一上报去重进度：保证【全局进度单调递增】并附带阶段 / ETA 信息。

    - phase_index: DEDUP_PHASES 中的阶段下标（0-based）
    - local_fraction: 当前阶段内部完成比例，范围 [0, 1]
    - extra: 合并进 _dedup_progress['details'] 的字段（completed / total / message / 块级信息等）

    全局进度 = 阶段起始% + 阶段权重% × local_fraction，并与历史最大值取 max，
    从而即使分块循环里「证据评分」每块的起点也不会让进度条回退。
    """
    global _dedup_progress
    local_fraction = max(0.0, min(1.0, float(local_fraction)))
    start_pct, end_pct = _DEDUP_PHASE_RANGE[phase_index]
    overall = start_pct + (end_pct - start_pct) * local_fraction
    # 单调递增保护：不同阶段 / 块之间绝不回退
    prev = _dedup_progress.get("overall_progress", 0.0)
    if overall < prev:
        overall = prev

    phase_name = DEDUP_PHASES[phase_index][0]

    # elapsed / ETA：基于 started_at 线性外推
    elapsed = None
    eta = None
    started = _dedup_progress.get("started_at")
    if started:
        try:
            started_ms = datetime.fromisoformat(started).timestamp()
            elapsed = max(0, int(time.time() - started_ms))
            if overall > 1:
                eta = int(elapsed * (100 - overall) / overall)
        except Exception:
            pass

    details: Dict[str, Any] = {
        "step_name": phase_name,
        "completed": 0,
        "total": 0,
        "message": "",
    }
    details.update(extra or {})

    # 阶段3（评分与写入队列）按已处理公司数估算吞吐：公司/秒
    throughput = None
    if phase_index == 3 and elapsed:
        done = details.get("completed") or 0
        if done > 0:
            throughput = round(done / elapsed, 1)

    _dedup_progress["phase_index"] = phase_index
    _dedup_progress["phase_name"] = phase_name
    _dedup_progress["phase_progress"] = round(local_fraction * 100, 2)
    _dedup_progress["overall_progress"] = round(overall, 2)
    _dedup_progress["progress"] = round(overall, 2)   # 向后兼容旧字段
    _dedup_progress["step"] = phase_name              # 向后兼容旧字段
    _dedup_progress["eta_seconds"] = eta
    _dedup_progress["elapsed_seconds"] = elapsed
    _dedup_progress["throughput"] = throughput
    _dedup_progress["details"] = details

# ─────────────────────────────────────────────────────────────────────────────
# SQLite Embeddings Cache
# ─────────────────────────────────────────────────────────────────────────────
# 项目根目录（backend/ 的上两级），用于定位 data/ 下的各类持久化缓存
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def get_cache_path() -> Path:
    """Get the path to the embeddings cache database."""
    cache_dir = _PROJECT_ROOT / "data"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir / "company_embeddings.db"


def init_embeddings_cache() -> None:
    """Initialize the SQLite embeddings cache database."""
    cache_path = get_cache_path()
    conn = sqlite3.connect(str(cache_path))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            company_name TEXT PRIMARY KEY,
            normalized_name TEXT,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_normalized_name
        ON embeddings(normalized_name)
    """)

    conn.commit()
    conn.close()
    logger.info(f"Initialized embeddings cache at {cache_path}")


# ──────────────────────────────────────────────────────────────────────────────
# Embedding 计算配置
# ──────────────────────────────────────────────────────────────────────────────
# 单次 API 请求包含的批次大小（一次 HTTP POST 携带的公司名条数）
# 越大吞吐越高，但响应体也越大（1536 维 × 条数），过大会触发网关超时导致整批回退 hash。
# 经验值 1000：响应约 25MB，120s 内稳定返回；相比 100 提速约 10 倍且风险可控。
EMBEDDING_BATCH_SIZE = 1000

# 单次 embedding API 请求的超时时间（秒）
EMBEDDING_REQUEST_TIMEOUT = 120.0

# 真实 embedding 模型的向量维度（text-embedding-3-small 为 1536）。
# hash 兜底的向量维度必须与之一致，否则部分批次回退时与真实向量维度不一致，
# 会导致 FAISS/暴力相似度阶段因混合维度而崩溃。若切换 embedding 模型（如
# text-embedding-3-large=3072），需同步修改本常量。
EMBEDDING_DIM = 1536

# Embedding API 并行计算的 worker 数（有界，避免压垮网关 / 触发限流）。
# 仅在配置了真实 API key 时启用；hash 兜底分支为纯 CPU、保持串行。
EMBEDDING_MAX_WORKERS = 4

# 去重写入阶段「按公司分块」的块大小：每处理完 DEDUP_WRITE_CHUNK 个公司，
# 就把这批公司的相似对评分并落库提交一次，作为检查点。崩溃时仅丢失当前块，
# 而非全部重新计算。1w 公司 ≈ 一次检查点，与全量 30w 的量级匹配。
DEDUP_WRITE_CHUNK = 10000

# 嵌入缓存库（SQLite）单写者锁：并行 worker 各自连接写入时需串行化，
# 否则并发写会触发 "database is locked"。
_EMB_CACHE_LOCK = threading.Lock()


def _hash_embedding(normalized: str, dim: int = EMBEDDING_DIM) -> np.ndarray:
    """hash 兜底：基于归一化名的确定性向量（dim 维，L2 归一化）。

    当 Embedding API 未配置或调用异常时使用，保证流程不中断。
    dim 必须与真实 embedding 模型维度一致（默认 EMBEDDING_DIM=1536），
    否则部分批次回退时与真实向量维度不一致，会导致相似度阶段崩溃。
    """
    vec = np.zeros(dim, dtype=np.float32)
    if not normalized:
        # 空名：返回零向量（归一化后仍是零向量），保持维度正确
        return vec
    for ch in normalized[:200]:
        vec[hash(ch) % dim] += 0.1
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def load_cached_embeddings(names: List[str], expected_dim: int = EMBEDDING_DIM) -> Dict[str, np.ndarray]:
    """批量加载缓存中的 embedding。

    以公司名为 key：精确匹配 company_name，或匹配 normalized_name（别名/错别字
    也能命中）。一次连接、分块 IN 查询，返回 {name: vector}（仅含命中项）。
    相比逐条查询，可将数万次连接/查询降为几次，大幅提升读取性能。

    expected_dim：期望的向量维度。维度不匹配的缓存行（如历史遗留的 128 维 hash
    向量）会被跳过当作未命中，交由后续计算补全，避免内存中混入异维向量导致
    FAISS/暴力相似度阶段因混合维度崩溃。
    """
    if not names:
        return {}

    raw_set = set(names)
    norm_to_names: Dict[str, List[str]] = defaultdict(list)
    for name in names:
        norm_to_names[normalize_company_name(name)].append(name)

    cache_path = get_cache_path()
    conn = sqlite3.connect(str(cache_path))
    try:
        cursor = conn.cursor()
        result: Dict[str, np.ndarray] = {}
        # SQLite 变量上限默认 999，IN 参数用两份（company_name + normalized_name），故分块 400
        CHUNK = 400
        for start in range(0, len(names), CHUNK):
            chunk = names[start:start + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            cursor.execute(
                f"SELECT company_name, normalized_name, embedding "
                f"FROM embeddings "
                f"WHERE company_name IN ({placeholders}) "
                f"OR normalized_name IN ({placeholders})",
                list(chunk) + list(chunk),
            )
            rows = cursor.fetchall()
            # 优先填精确命中（company_name 命中）
            for company_name, normalized_name, blob in rows:
                if company_name in raw_set and company_name not in result:
                    vec = np.frombuffer(blob, dtype=np.float32)
                    if len(vec) != expected_dim:
                        continue  # 维度不匹配（如旧 128 维缓存），当作未命中
                    result[company_name] = vec
            # 再填归一化命中（不覆盖已精确命中的项）
            for company_name, normalized_name, blob in rows:
                if normalized_name in norm_to_names:
                    vec = np.frombuffer(blob, dtype=np.float32)
                    if len(vec) != expected_dim:
                        continue  # 维度不匹配，跳过，避免混入异维向量
                    for name in norm_to_names[normalized_name]:
                        if name not in result:
                            result[name] = vec
        return result
    finally:
        conn.close()


def save_embeddings_batch(records: List[Tuple[str, str, np.ndarray]]) -> int:
    """一次性批量写入新计算的 embedding（单连接 + executemany 单事务）。

    在所有未命中项统一计算完成后调用，避免“计算一条写一条”的频繁连接/提交
    开销。records: List of (company_name, normalized_name, vector)。返回写入行数。
    """
    if not records:
        return 0

    cache_path = get_cache_path()
    conn = sqlite3.connect(str(cache_path))
    try:
        cursor = conn.cursor()
        cursor.executemany(
            "REPLACE INTO embeddings "
            "(company_name, normalized_name, embedding, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            [(name, norm, vec.tobytes()) for name, norm, vec in records],
        )
        conn.commit()
        return len(records)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────────

def normalize_company_name(name: str) -> str:
    """
    Clean and standardize a company name by removing common suffixes,
    legal forms, and noise.

    Args:
        name: Raw company name

    Returns:
        Normalized company name
    """
    if not name or not isinstance(name, str):
        return ""

    # Convert to lowercase and strip whitespace
    normalized = name.strip().lower()

    # Remove punctuation and special characters
    normalized = re.sub(r'[^\w\s一-鿿]', ' ', normalized)

    # Remove multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # English suffixes to remove
    english_suffixes = [
        r'\bco\b', r'\binc\b', r'\bltd\b', r'\bllc\b', r'\bcorp\b',
        r'\bcorporation\b', r'\bcompany\b', r'\blimited\b', r'\bgmbh\b',
        r'\bsa\b', r'\bag\b', r'\bgroup\b', r'\bholdings\b', r'\bholding\b',
        r'\btechnologies\b', r'\btech\b', r'\bsystems\b', r'\bsolutions\b',
        r'\binternational\b', r'\bintl\b',
    ]

    # Chinese suffixes to remove
    chinese_suffixes = [
        '有限公司', '股份有限公司', '有限责任公司', '集团', '控股',
        '科技', '技术', '实业', '投资', '贸易', '发展', '实业',
        '股份', '责任', '公司', '集团有限公司', '控股集团',
        '科技有限公司', '技术有限公司', '实业有限公司',
        '投资有限公司', '贸易有限公司', '发展有限公司',
    ]

    # Remove Chinese suffixes
    for suffix in chinese_suffixes:
        normalized = normalized.replace(suffix, '')

    # Remove English suffixes
    for suffix in english_suffixes:
        normalized = re.sub(suffix, '', normalized)

    # Remove parentheses content (common location info)
    normalized = re.sub(r'\([^)]*\)', '', normalized)
    normalized = re.sub(r'（[^）]*）', '', normalized)

    # Clean up again
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    return normalized


# ─────────────────────────────────────────────────────────────────────────────
# Embeddings Computation (Simulated with Semantic Hash + Random)
# ─────────────────────────────────────────────────────────────────────────────

def _semantic_hash(text: str, dim: int = 64) -> np.ndarray:
    """
    Generate a deterministic semantic hash vector.
    Uses character n-grams and hashing to create a vector.
    """
    vector = np.zeros(dim, dtype=np.float32)

    # Use character n-grams
    for n in range(2, 5):
        for i in range(len(text) - n + 1):
            ngram = text[i:i + n]
            # Hash the ngram to get an index
            h = hashlib.md5(ngram.encode('utf-8')).hexdigest()
            idx = int(h, 16) % dim
            # Increment based on character values
            weight = sum(ord(c) for c in ngram) / (n * 1000.0)
            vector[idx] += weight

    # Add word-level features
    words = text.split()
    for word in words:
        h = hashlib.md5(word.encode('utf-8')).hexdigest()
        idx = int(h, 16) % dim
        vector[idx] += 1.0

    return vector


def compute_embeddings_batch(names: List[str], progress_callback: Optional[Callable[[int, int, Optional[str]], None]] = None) -> List[np.ndarray]:
    """
    Compute embeddings for a batch of company names using real API.
    Results cached in SQLite to avoid recomputation.

    Args:
        names: List of company names
        progress_callback: Optional callback (completed, total, message=None) 上报进度；
            每批发起网络请求前也会上报一次（带批号），避免整批计算期间前端无反馈。

    Returns:
        List of embedding vectors (1536-dim for text-embedding-3-small)
    """
    from app.config import settings

    init_embeddings_cache()

    # 1) 批量读缓存：命中项直接复用，未命中项才进入计算（一次连接分块 IN 查询，
    #    避免逐条 open/close 连接，数万公司名也能秒级完成）。
    cached_map = load_cached_embeddings(names)
    embeddings: List[Optional[np.ndarray]] = [cached_map.get(name) for name in names]
    uncached_indices: List[int] = [i for i, e in enumerate(embeddings) if e is None]
    uncached_names: List[str] = [names[i] for i in uncached_indices]

    cached_count = len(cached_map)

    # 全部命中，直接返回（进度一次置满，无需调用 API）
    if not uncached_names:
        if progress_callback:
            progress_callback(len(names), len(names))
        logger.info("Embedding 全部命中本地缓存，跳过 API 调用（%d 条）", cached_count)
        return cast(List[np.ndarray], embeddings)

    # 2) 计算未命中项：优先 Embedding API，缺失配置或调用异常时回退 hash 兜底。
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL

    if not api_key or not base_url:
        # 无 API 配置：纯 CPU 的 hash 兜底，保持串行（快速，无需并行）。
        logger.warning("Embedding API 未配置，使用 hash embedding 兜底")
        for i, idx in enumerate(uncached_indices):
            name = names[idx]
            embeddings[idx] = _hash_embedding(normalize_company_name(name), EMBEDDING_DIM)
            if progress_callback:
                progress_callback(cached_count + i + 1, len(names))
        logger.info("Embedding 计算完成（全 hash 兜底）：本地缓存命中 %d 条", cached_count)
        return cast(List[np.ndarray], embeddings)

    # 配置了真实 API：使用有界线程池并行请求以最大化吞吐（网络瓶颈）。
    # 各 worker 把结果按各自索引写入共享 embeddings 列表（索引互不重叠，GIL 下安全），
    # 并各自带 _EMB_CACHE_LOCK 写 SQLite 缓存；进度用原子计数 + 锁聚合，避免竞态。
    # 每批计算完即写缓存（而非末尾统一写），单批失败仅回退该批、且已算批次已持久化。
    resolved_url = f"{base_url.rstrip('/')}/embeddings"
    batch_size = EMBEDDING_BATCH_SIZE
    done = [0]  # 用列表承载跨线程计数（int 不可 nonlocal 于嵌套函数）
    done_lock = threading.Lock()

    def _process_batch(batch_indices: List[int]) -> None:
        """处理一批（串行请求 API 或 hash 回退），写共享结果与缓存。"""
        batch_names = [names[i] for i in batch_indices]
        rows = []  # 待写缓存的 (name, normalized, vec)
        try:
            with httpx.Client(timeout=EMBEDDING_REQUEST_TIMEOUT) as client:
                resp = client.post(
                    resolved_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.EMBEDDING_MODEL,
                        "input": batch_names,
                        "encoding_format": "float",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("data", []):
                    pos = item.get("index", 0)
                    gi = batch_indices[pos]
                    emb = np.array(item["embedding"], dtype=np.float32)
                    norm = np.linalg.norm(emb)
                    if norm > 0:
                        emb = emb / norm
                    embeddings[gi] = emb  # 索引互不重叠，GIL 下安全
                    rows.append((names[gi], normalize_company_name(names[gi]), emb))
        except Exception as e:
            logger.warning(
                "Embedding API 调用失败（batch %d 条），回退 hash 兜底: %s",
                len(batch_indices), e,
            )
            for gi in batch_indices:
                emb = _hash_embedding(normalize_company_name(names[gi]), EMBEDDING_DIM)
                embeddings[gi] = emb
                rows.append((names[gi], normalize_company_name(names[gi]), emb))

        # 写缓存（SQLite 单写者，需串行化）
        if rows:
            with _EMB_CACHE_LOCK:
                save_embeddings_batch(rows)

        # 聚合进度（线程安全）
        with done_lock:
            done[0] += len(batch_indices)
            completed = cached_count + done[0]
        if progress_callback:
            progress_callback(
                completed,
                len(names),
                "正在计算嵌入向量... (已完成 {}/{} 条)".format(completed, len(names)),
            )

    batches = [uncached_indices[s:s + batch_size] for s in range(0, len(uncached_indices), batch_size)]
    with ThreadPoolExecutor(max_workers=EMBEDDING_MAX_WORKERS) as ex:
        futures = [ex.submit(_process_batch, b) for b in batches]
        for fut in as_completed(futures):
            fut.result()  # worker 内部已捕获异常，这里仅确保未处理异常不遗漏

    logger.info(
        "Embedding 计算完成：本地缓存命中 %d 条，并行计算 %d 条（workers=%d）",
        cached_count,
        len(uncached_indices),
        EMBEDDING_MAX_WORKERS,
    )
    return cast(List[np.ndarray], embeddings)


# ─────────────────────────────────────────────────────────────────────────────
# Cosine Similarity
# ─────────────────────────────────────────────────────────────────────────────

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))


# ─────────────────────────────────────────────────────────────────────────────
# FAISS 快速相似度搜索（可选依赖）
# ─────────────────────────────────────────────────────────────────────────────

try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False


def find_similar_pairs_faiss(
    embeddings: List[np.ndarray],
    names: List[str],
    threshold: float = 0.85,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[Tuple[int, int, float]]:
    """
    使用 FAISS 进行快速余弦相似度搜索。

    相比暴力搜索 O(n²)，FAISS 索引搜索复杂度为 O(n log n)，
    在 10,000 家公司规模下可提速约 770 倍。

    Args:
        embeddings: 嵌入向量列表（必须维度一致）
        names: 公司名列表
        threshold: 最低相似度阈值
        progress_callback: 进度回调 (completed, total, message)

    Returns:
        List of (index_a, index_b, similarity_score)
    """
    n = len(embeddings)
    if n < 2:
        return []

    dim = len(embeddings[0])
    # 构建 numpy 数组
    emb_array = np.array([e.astype(np.float32) for e in embeddings])

    # 使用内积索引（余弦相似度 = 内积 / (|a|*|b|)，向量已 L2 归一化则内积=余弦）
    if progress_callback:
        progress_callback(0, n, f"构建 FAISS 索引中... ({n} 个向量)")
    index = faiss.IndexFlatIP(dim)
    index.add(emb_array)

    # 每个向量搜索 k 个最近邻（包含自身）
    k = min(n, FAISS_K_NEAREST_NEIGHBORS)
    if progress_callback:
        progress_callback(0, n, f"FAISS 搜索最近邻中... (k={k})")
    distances, indices = index.search(emb_array, k)

    pairs: List[Tuple[int, int, float]] = []
    seen: set = set()

    # 构建精确归一化匹配
    name_to_indices: Dict[str, List[int]] = defaultdict(list)
    for i, name in enumerate(names):
        norm = normalize_company_name(name)
        if norm:
            name_to_indices[norm].append(i)

    # 先添加精确归一化匹配
    for normalized, idx_list in name_to_indices.items():
        if len(idx_list) > 1:
            for a in range(len(idx_list)):
                for b in range(a + 1, len(idx_list)):
                    pair_key = (min(idx_list[a], idx_list[b]),
                                max(idx_list[a], idx_list[b]))
                    if pair_key not in seen:
                        seen.add(pair_key)
                        pairs.append((idx_list[a], idx_list[b], 0.98))

    # 从 FAISS 结果中提取相似对
    if progress_callback:
        progress_callback(0, n, f"提取相似对中... ({n} 个公司)")
    progress_step = max(1, n // 20)  # 每 5% 更新一次
    for i in range(n):
        if progress_callback and i % progress_step == 0:
            progress_callback(i, n, f"提取相似对: {i}/{n} (已找到 {len(pairs)} 对)")
        for j_idx in range(k):
            j = int(indices[i][j_idx])
            if j < 0 or j >= n:
                continue
            sim = float(distances[i][j_idx])
            if sim < threshold:
                continue
            if i >= j:
                continue

            # 跳过已处理的精确匹配
            norm_i = normalize_company_name(names[i])
            norm_j = normalize_company_name(names[j])
            if norm_i == norm_j and norm_i:
                continue

            pair_key = (i, j)
            if pair_key not in seen:
                seen.add(pair_key)
                pairs.append((i, j, sim))

    if progress_callback:
        progress_callback(n, n, f"FAISS 提取完成: {len(pairs)} 个相似对")

    # 按相似度降序排序
    pairs.sort(key=lambda x: x[2], reverse=True)
    
    return pairs


def find_similar_pairs(
    embeddings: List[np.ndarray],
    names: List[str],
    threshold: float = 0.85,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[Tuple[int, int, float]]:
    """
    查找相似公司对。优先使用 FAISS 加速，不可用时回退到暴力搜索。

    Args:
        embeddings: 嵌入向量列表
        names: 公司名列表
        threshold: 最低相似度阈值
        progress_callback: 进度回调 (completed, total, message)

    Returns:
        List of (index_a, index_b, similarity_score)
    """
    n = len(embeddings)
    if n < 100:
        # 小数据集直接暴力搜索，FAISS 开销不划算
        return _find_similar_pairs_bruteforce(embeddings, names, threshold, progress_callback)

    # 检查所有向量维度是否一致
    dims = {len(e) for e in embeddings}
    if _FAISS_AVAILABLE and len(dims) == 1:
        try:
            logger.info(f"Using FAISS for similarity search on {n} vectors "
                        f"(dim={dims.pop()})")
            return find_similar_pairs_faiss(embeddings, names, threshold, progress_callback)
        except Exception as e:
            logger.warning(f"FAISS search failed, falling back to brute force: {e}")

    logger.info(f"Using brute-force similarity search on {n} vectors")
    return _find_similar_pairs_bruteforce(embeddings, names, threshold, progress_callback)


def _find_similar_pairs_bruteforce(
    embeddings: List[np.ndarray],
    names: List[str],
    threshold: float = 0.85,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[Tuple[int, int, float]]:
    """暴力 O(n²) 相似度搜索（备用方案），使用 numpy 向量化加速。"""
    pairs: List[Tuple[int, int, float]] = []
    n = len(embeddings)
    total_pairs = n * (n - 1) // 2

    # 预转换为 numpy 矩阵，以便向量化计算
    emb_array = np.array([e.astype(np.float32) for e in embeddings])  # shape (n, dim)

    # 构建归一化名称索引，找出精确匹配
    name_to_indices: Dict[str, List[int]] = defaultdict(list)
    for i, name in enumerate(names):
        normalized = normalize_company_name(name)
        if normalized:
            name_to_indices[normalized].append(i)

    # 精确归一化匹配给高优先级
    for normalized, indices in name_to_indices.items():
        if len(indices) > 1:
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    pairs.append((indices[i], indices[j], 0.98))

    # 对所有其他对计算余弦相似度（向量化批量计算）
    checked = 0
    progress_report_every = max(1, total_pairs // 200)  # 每 0.5% 的对比量汇报一次
    next_report = progress_report_every

    for i in range(n - 1):
        # 向量化：一次计算 row_i 与所有 row_{i+1..n-1} 的余弦相似度
        # emb_array 已经 L2 归一化过，所以点积 = 余弦相似度
        sims = np.dot(emb_array[i + 1:], emb_array[i])  # shape: (n - i - 1,)
        batch_checked = len(sims)
        checked += batch_checked

        # 找到超过阈值的
        candidates = np.where(sims >= threshold)[0]
        for j_offset in candidates:
            j = i + 1 + int(j_offset)
            # 跳过精确归一化匹配的情况
            norm_i = normalize_company_name(names[i])
            norm_j = normalize_company_name(names[j])
            if norm_i == norm_j and norm_i:
                continue
            pairs.append((i, j, float(sims[j_offset])))

        # 进度上报：基于累计对比数量，而非外层循环次数
        if progress_callback and checked >= next_report:
            next_report = checked + progress_report_every
            pct = checked * 100.0 / total_pairs if total_pairs > 0 else 100
            progress_callback(i + 1, n, 
                f"向量化搜索: {i+1}/{n} 公司 ({checked}/{total_pairs} 对={pct:.1f}%, 找到{len(pairs)}对)")

    if progress_callback:
        progress_callback(n, n, f"向量化搜索完成: 共对比 {checked} 对, 找到 {len(pairs)} 个相似对")

    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based Similarity Score
# ─────────────────────────────────────────────────────────────────────────────

def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]

def calculate_rule_score(name_a: str, name_b: str) -> float:
    """
    Calculate rule-based similarity score.

    Factors:
    - Levenshtein distance (编辑距离相似度)
    - Substring containment (子串包含)
    - Common prefix/suffix (公共前缀/后缀)
    - Shared tokens (共享词汇)
    - Character-level Jaccard similarity (字符级Jaccard相似度)

    Args:
        name_a: First company name
        name_b: Second company name

    Returns:
        Score between 0 and 100
    """
    norm_a = normalize_company_name(name_a)
    norm_b = normalize_company_name(name_b)

    if not norm_a or not norm_b:
        return 0.0

    # Exact match after normalization
    if norm_a == norm_b:
        return 100.0

    scores: List[float] = []
    
    # 1. Levenshtein distance based similarity
    max_len = max(len(norm_a), len(norm_b))
    if max_len > 0:
        lev_dist = _levenshtein(norm_a, norm_b)
        lev_score = (1 - lev_dist / max_len) * 100
        scores.append(lev_score * RULE_LEVENSHTEIN_WEIGHT)

    # 2. Substring containment - 允许与其他特征叠加
    if norm_a in norm_b:
        containment = len(norm_a) / len(norm_b) * 100
        scores.append(containment * RULE_SUBSTRING_WEIGHT)
    if norm_b in norm_a:
        containment = len(norm_b) / len(norm_a) * 100
        scores.append(containment * RULE_SUBSTRING_WEIGHT)

    # 3. Common prefix/suffix
    # 公共前缀
    prefix_len = 0
    for i in range(min(len(norm_a), len(norm_b))):
        if norm_a[i] == norm_b[i]:
            prefix_len += 1
        else:
            break
    if prefix_len > 0:
        prefix_score = (prefix_len / max(len(norm_a), len(norm_b))) * 100
        scores.append(prefix_score * RULE_PREFIX_WEIGHT)
    
    # 公共后缀
    suffix_len = 0
    for i in range(1, min(len(norm_a), len(norm_b)) + 1):
        if norm_a[-i] == norm_b[-i]:
            suffix_len += 1
        else:
            break
    if suffix_len > 0:
        suffix_score = (suffix_len / max(len(norm_a), len(norm_b))) * 100
        scores.append(suffix_score * RULE_SUFFIX_WEIGHT)

    # 4. Token-based similarity
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    if tokens_a and tokens_b:
        common_tokens = len(tokens_a & tokens_b)
        total_tokens = len(tokens_a | tokens_b)
        if total_tokens > 0:
            token_score = (common_tokens / total_tokens) * 100
            scores.append(token_score * RULE_TOKEN_WEIGHT)

    # 5. Character-level Jaccard similarity
    set_a = set(norm_a)
    set_b = set(norm_b)
    if set_a or set_b:
        common_chars = len(set_a & set_b)
        total_chars = len(set_a | set_b)
        if total_chars > 0:
            jaccard = (common_chars / total_chars) * 100
            scores.append(jaccard * RULE_JACCARD_WEIGHT)

    # Combine scores (允许累加，但上限100)
    final_score = min(100.0, sum(scores))

    return round(final_score, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Evidence-based Score (Shared Contacts)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_evidence_score(name_a: str, name_b: str, db: Session) -> tuple:
    """
    计算单对公司的证据评分（基于多个表的共享联系人和共享信息）。
    对于批量场景，建议使用 batch_calculate_evidence_scores 以获得更好性能。

    Args:
        name_a: 公司A名称
        name_b: 公司B名称
        db: 数据库会话

    Returns:
        (evidence_score, evidence_count)
    """
    evidence_score = 0.0
    evidence_count = 0

    # 定义要检查的表和字段：直接使用 dws 聚合表（不再读 ods）
    tables_to_check = EVIDENCE_TABLES

    try:
        total_shared = 0
        
        for table_config in tables_to_check:
            table_name = table_config["table"]
            company_field = table_config["company_field"]
            phone_field = table_config["phone_field"]
            email_field = table_config["email_field"]
            
            # 检查共享电话
            phone_sql = text(f"""
                SELECT COUNT(DISTINCT c1.{phone_field}) as shared_phones
                FROM {table_name} c1
                JOIN {table_name} c2 ON c1.{phone_field} = c2.{phone_field}
                WHERE c1.{company_field} LIKE :name_a
                  AND c2.{company_field} LIKE :name_b
                  AND c1.{phone_field} IS NOT NULL AND c1.{phone_field} != ''
            """)

            # 检查共享邮箱（仅当该表含邮箱字段；dws_interaction_detail 无邮箱列）
            email_result = 0
            if email_field:
                email_sql = text(f"""
                    SELECT COUNT(DISTINCT c1.{email_field}) as shared_emails
                    FROM {table_name} c1
                    JOIN {table_name} c2 ON c1.{email_field} = c2.{email_field}
                    WHERE c1.{company_field} LIKE :name_a
                      AND c2.{company_field} LIKE :name_b
                      AND c1.{email_field} IS NOT NULL AND c1.{email_field} != ''
                """)
                email_result = db.execute(
                    email_sql, {"name_a": f"%{name_a}%", "name_b": f"%{name_b}%"}
                ).scalar() or 0

            phone_result = db.execute(
                phone_sql, {"name_a": f"%{name_a}%", "name_b": f"%{name_b}%"}
            ).scalar() or 0

            total_shared += phone_result + email_result
        
        if total_shared > 0:
            evidence_score = min(100.0, total_shared * EVIDENCE_SCORE_MULTIPLIER)
            evidence_count = total_shared

    except Exception as e:
        logger.warning(f"Error calculating evidence score: {e}")
        evidence_score = 0.0

    return round(evidence_score, 2), evidence_count


def _safe_fetchall(db, sql, params, label, log, max_retry=3):
    """执行只读查询并在连接失活（2013 / PendingRollbackError）时回滚并重试。

    关键：连接断开（2013）后会话会进入 invalid 事务状态，若不先 rollback 就再次 execute，
    会持续抛 PendingRollbackError 且无法重连。故捕获后先 db.rollback() 清状态再重试；
    非连接类错误（如字段/SQL 错误）不重试，直接降级返回 None，保持单表失败不影响整体。
    """
    last_exc = None
    for attempt in range(max_retry):
        try:
            return db.execute(sql, params).fetchall()
        except (OperationalError, PendingRollbackError) as _e:
            last_exc = _e
            log.warning("%s 查询连接失活（第 %d 次），回滚并重试: %s", label, attempt + 1, _e)
            try:
                db.rollback()
            except Exception:
                pass
        except Exception as _e:
            log.warning("%s 查询失败（非连接错误），跳过该查询: %s", label, _e)
            return None
    log.warning("%s 查询连接重试 %d 次仍失败，跳过: %s", label, max_retry, last_exc)
    return None


def _match_orig_name(
    company_name: Optional[str],
    exact_lookup: set,
    all_companies: List[str],
) -> Optional[str]:
    """把联系行里的公司名匹配回去重目标公司名。

    快路径：精确相等 O(1)（dws_contact_mapping 等来源的公司名通常与 dws_customer_360
    完全一致，占绝大多数）。未精确命中时回退到原始「双向子串 + 规范化相等」扫描，
    语义与原实现完全一致，仅把常见情形从 O(公司数) 降到 O(1)，极大减少全量运行耗时。
    """
    if company_name and company_name in exact_lookup:
        return company_name
    if not company_name:
        return None
    for orig_name in all_companies:
        if orig_name in company_name:
            return orig_name
    for orig_name in all_companies:
        if orig_name and (
            company_name in orig_name
            or normalize_company_name(company_name) == normalize_company_name(orig_name)
        ):
            return orig_name
    return None


def batch_calculate_evidence_scores(
    company_pairs: List[Tuple[str, str]],
    db: Session,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[Tuple[str, str], Tuple[float, int]]:
    """
    批量计算多对公司证据评分，大幅减少数据库查询次数。
    支持多个ODS表的共享联系人和共享信息检查。

    Args:
        company_pairs: [(company_a_name, company_b_name), ...]
        db: 数据库会话
        progress_callback: 进度回调 (completed, total, message)

    Returns:
        {(name_a, name_b): (evidence_score, shared_contacts_count), ...}
    """
    if not company_pairs:
        return {}

    total_pairs = len(company_pairs)

    # 收集所有公司名
    all_companies = set()
    for name_a, name_b in company_pairs:
        all_companies.add(name_a)
        all_companies.add(name_b)

    # 定义要检查的表（直接使用 dws 聚合表，不再读 ods）
    tables_to_check = EVIDENCE_TABLES

    # 聚合所有公司的联系信息
    company_phones: Dict[str, set] = defaultdict(set)
    company_emails: Dict[str, set] = defaultdict(set)
    # 共用电话/邮箱 → 联系人姓名（取第一个非空姓名）
    phone_to_name: Dict[str, str] = {}
    email_to_name: Dict[str, str] = {}

    num_tables = len(tables_to_check)
    for table_idx, table_config in enumerate(tables_to_check):
        table_name = table_config["table"]
        company_field = table_config["company_field"]
        phone_field = table_config["phone_field"]
        email_field = table_config["email_field"]
        name_field = table_config.get("name_field", "contact_name")

        # 进度：告知前端正在查询哪个表
        if progress_callback:
            progress_callback(0, total_pairs,
                             f"正在查询 {table_name} 的联系数据 ({table_idx + 1}/{num_tables})...")

        # 使用精确 IN 匹配（按公司名精确匹配），避免对每个公司名生成一条
        # "字段 LIKE :name_N" 条件并用 OR 串联，导致公司数上千时产生巨型 SQL
        # (如 related_company LIKE %(name_1366)s OR ...)，既臃肿又会造成匹配漂移
        # 与严重性能问题。模糊匹配（子串/归一化）仍由下方 Python 逻辑处理。
        name_list = list(all_companies)
        placeholders = ", ".join([f":name_{idx}" for idx in range(len(name_list))])
        params: Dict[str, str] = {
            f"name_{idx}": name for idx, name in enumerate(name_list)
        }
        in_clause = f"{company_field} IN ({placeholders})" if placeholders else "1=0"

        # 批量查询：公司 → 电话集合，同时记录电话→姓名
        phone_sql = text(f"""
            SELECT {company_field}, {phone_field}, {name_field}
            FROM {table_name}
            WHERE ({in_clause})
              AND {phone_field} IS NOT NULL AND {phone_field} != ''
        """)
        phone_rows = _safe_fetchall(db, phone_sql, params, f"{table_name} 电话", logger)
        if phone_rows is not None:
            for company_name, phone, contact_name in phone_rows:
                # 记录电话→姓名（去空格后非空才存）
                if contact_name:
                    cn_clean = str(contact_name).strip()
                    if cn_clean and phone not in phone_to_name:
                        phone_to_name[phone] = cn_clean
                # 匹配回原始公司名（精确 O(1) 快路径 + 模糊回退，语义不变）
                orig = _match_orig_name(company_name, all_companies, name_list)
                if orig:
                    company_phones[orig].add(phone)

        if progress_callback:
            progress_callback(0, total_pairs,
                             f"已完成 {table_name} 电话查询 ({table_idx + 1}/{num_tables})，正在查邮箱...")

        # 批量查询：公司 → 邮箱集合，同时记录邮箱→姓名
        # 注意：dws_interaction_detail 等聚合表可能没有邮箱字段（email_field=None），
        # 此时跳过邮箱查询，避免拼出非法 SQL。
        email_rows: list = []
        if email_field:
            email_sql = text(f"""
                SELECT {company_field}, {email_field}, {name_field}
                FROM {table_name}
                WHERE ({in_clause})
                  AND {email_field} IS NOT NULL AND {email_field} != ''
            """)
            email_rows = _safe_fetchall(db, email_sql, params, f"{table_name} 邮箱", logger) or []
        if email_rows:
            for company_name, email, contact_name in email_rows:
                # 记录邮箱→姓名
                if contact_name:
                    cn_clean = str(contact_name).strip()
                    if cn_clean and email not in email_to_name:
                        email_to_name[email] = cn_clean
                # 匹配回原始公司名（精确 O(1) 快路径 + 模糊回退，语义不变）
                orig = _match_orig_name(company_name, all_companies, name_list)
                if orig:
                    company_emails[orig].add(email)

        if progress_callback:
            progress_callback(0, total_pairs,
                             f"已完成 {table_name} 查询 ({table_idx + 1}/{num_tables})")

    # 所有表查询完成，开始计算共享联系人
    if progress_callback:
        progress_callback(0, total_pairs, "数据收集完成，正在计算共享联系人...")

    # 在内存中计算每对的共享联系人和详情
    scores: Dict[Tuple[str, str], Tuple[float, int, List[Dict[str, str]]]] = {}
    if progress_callback:
        progress_callback(0, total_pairs, "正在从数据库收集证据...")
    # 每 100 对更新一次进度，并添加微小延迟让前端轮询能捕获到中间状态
    for pair_idx, (name_a, name_b) in enumerate(company_pairs):
        phones_a = company_phones.get(name_a, set())
        phones_b = company_phones.get(name_b, set())
        emails_a = company_emails.get(name_a, set())
        emails_b = company_emails.get(name_b, set())

        shared_phone_values = phones_a & phones_b
        shared_email_values = emails_a & emails_b
        shared_phones = len(shared_phone_values)
        shared_emails = len(shared_email_values)
        shared_contacts = shared_phones + shared_emails

        if shared_contacts > 0:
            evidence_score = min(100.0, shared_contacts * EVIDENCE_SCORE_MULTIPLIER)
        else:
            evidence_score = 0.0

        # 收集共享联系人详情（去重姓名）
        shared_details: List[Dict[str, str]] = []
        seen_names: set = set()
        for phone in shared_phone_values:
            contact_name = phone_to_name.get(phone, phone)
            if contact_name not in seen_names:
                seen_names.add(contact_name)
                shared_details.append({"name": contact_name, "value": phone, "type": "phone"})
        for email in shared_email_values:
            contact_name = email_to_name.get(email, email)
            if contact_name not in seen_names:
                seen_names.add(contact_name)
                shared_details.append({"name": contact_name, "value": email, "type": "email"})

        scores[(name_a, name_b)] = (round(evidence_score, 2), shared_contacts, shared_details)

        if progress_callback and pair_idx % 100 == 0:
            progress_callback(
                pair_idx + 1, total_pairs,
                f"正在计算证据评分... ({pair_idx + 1}/{total_pairs})"
            )
            # 微延迟让前端 1 秒轮询有机会捕获进度变化
            time.sleep(0.003)

    if progress_callback:
        progress_callback(total_pairs, total_pairs, f"证据评分完成: {total_pairs} 对")

    return scores


# ─────────────────────────────────────────────────────────────────────────────
# LLM Judge
# ─────────────────────────────────────────────────────────────────────────────

def llm_judge(name_a: str, name_b: str,
              rule_score: float, evidence_score: float,
              api_key: str = "", base_url: str = "") -> tuple[float, str]:
    """
    Use LLM to determine if two company names refer to the same entity.

    Args:
        name_a, name_b: Company names to compare
        rule_score, evidence_score: Pre-calculated scores (0-100)
        api_key, base_url: LLM API configuration

    Returns:
        (llm_score 0-1, explanation_text)
    """
    # Fallback: if no API key provided, use rule+evidence as proxy
    if not api_key:
        proxy = (rule_score * LLM_FALLBACK_RULE_WEIGHT + evidence_score * LLM_FALLBACK_EVIDENCE_WEIGHT) / 100.0
        return (min(1.0, max(0.0, proxy)),
                "LLM not configured; score derived from rule + evidence")

    prompt = f"""You are a company-name matching expert. Determine whether the following
two company names refer to the same business entity.

Company A: "{name_a}"
Company B: "{name_b}"

Consider these aspects:
1. ABBREVIATION / FULL NAME — e.g. "阿里" vs "阿里巴巴集团控股有限公司" → likely same
2. SUBSIDIARY RELATIONSHIPS — e.g. "字节跳动" vs "北京字节跳动科技有限公司" → likely same
3. DISTINCT LEGAL ENTITIES — e.g. "华为技术有限公司" vs "华为投资控股有限公司" → different entities
   (same brand, different legal persons)
4. EVIDENCE — shared phones/emails suggest the same entity

Pre-computed similarity hints:
- Rule-based name similarity (0-100): {rule_score}/100
- Evidence-based contact overlap (0-100): {evidence_score}/100

Output ONLY a single number between 0 and 1 representing your confidence
that these are the same company, followed by a brief explanation on the
same line, separated by a pipe character "|".

Examples:
0.95 | Same entity: full name vs abbreviation
0.30 | Different legal entities under the same brand
0.85 | Subsidiary relationship with shared evidence
0.10 | Completely unrelated companies
"""

    try:
        client = LLMClient(api_key=api_key, base_url=base_url)
        content = client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100,
        )
        if content is None:
            raise RuntimeError("LLM 返回为空")
    except Exception as e:
        logger.warning(f"LLM judge call failed: {e}")
        # Fallback on error
        proxy = (rule_score * LLM_FALLBACK_RULE_WEIGHT + evidence_score * LLM_FALLBACK_EVIDENCE_WEIGHT) / 100.0
        return (min(1.0, max(0.0, proxy)), f"LLM call failed ({e}); fallback score")

    # Parse response: expect "0.95 | explanation"
    if "|" in content:
        score_str, explanation = content.split("|", 1)
        score_str = score_str.strip()
        explanation = explanation.strip()
    else:
        # Try to extract a number from the first token
        tokens = content.split()
        score_str = tokens[0] if tokens else "0"
        explanation = content

    try:
        llm_score = float(score_str)
        llm_score = min(1.0, max(0.0, llm_score))
    except (ValueError, TypeError):
        llm_score = (rule_score * LLM_FALLBACK_RULE_WEIGHT + evidence_score * LLM_FALLBACK_EVIDENCE_WEIGHT) / 100.0
        explanation = f"Could not parse LLM output; fallback score"

    return (llm_score, explanation)


# ─────────────────────────────────────────────────────────────────────────────
# Final Score Calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_final_score(
    rule_score: float,
    evidence_score: float,
    embedding_similarity: float,
    llm_score: float = 0
) -> float:
    """
    Calculate weighted final score.

    Weights (matching document section 10.2):
    - Rule-based: 30%
    - Evidence-based: 30%
    - LLM score: 40%

    ``llm_score`` replaces ``embedding_similarity`` as the primary differentiator.
    Embedding remains available as supplementary data only.

    Args:
        rule_score: Rule-based score (0-100)
        evidence_score: Evidence-based score (0-100)
        embedding_similarity: Embedding cosine similarity (0-1, supplementary)
        llm_score: LLM confidence score (0-100, default 0)

    Returns:
        Final score between 0 and 100
    """
    # 调整权重：降低LLM权重从40%到25%，增加evidence权重从30%到40%
    final_score = (
        rule_score * FINAL_RULE_WEIGHT +
        evidence_score * FINAL_EVIDENCE_WEIGHT +
        llm_score * FINAL_LLM_WEIGHT
    )

    return round(min(100.0, final_score), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Fetch Company Names
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_company_names(db: Session) -> List[Dict[str, Any]]:
    """
    Fetch all unique company names from all sources.
    照搬旧版 company_dedup_wasted.py 的数据读取逻辑（表字段名与旧版保持一致）。

    Sources（仅 dws 四张聚合表，不再直接读 ods）：
    - dws_customer_360：客户360宽表（主体，含真实客户 id）
    - dws_contact_mapping：联系人映射聚合表（含各 ods 联系人来源的公司名）
    - dws_interaction_detail：互动明细聚合表（含各 ods 互动来源的公司名）
    - dws_contact_360：仅含 customer_id 无公司名列，不参与公司名发现

    Args:
        db: Database session

    Returns:
        List of dicts with company name and source info
    """
    import time
    companies: Dict[str, Dict[str, Any]] = {}
    total_start = time.time()

    logger.info("=" * 60)
    logger.info("开始获取公司名称...")
    logger.info("=" * 60)

    # Source 1: dws_customer_360（主体宽表，含真实客户 id）
    try:
        t0 = time.time()
        logger.info("[1/3] 查询 dws_customer_360...")
        sql1 = text("""
            SELECT DISTINCT customer_name, id
            FROM dws_customer_360
            WHERE customer_name IS NOT NULL AND customer_name != ''
        """)
        result1 = db.execute(sql1).fetchall()
        for _raw_name, row_id in result1:
            row_name = clean_company_symbols(_raw_name)
            if not row_name:
                continue
            src_entry = {"table": "dws_customer_360", "record_id": row_id}
            if row_name not in companies:
                companies[row_name] = {
                    "name": row_name,
                    "customer_id": row_id,
                    "sources": [src_entry],
                }
            else:
                existing_tables = {s["table"] if isinstance(s, dict) else s for s in companies[row_name]["sources"]}
                if "dws_customer_360" not in existing_tables:
                    companies[row_name]["sources"].append(src_entry)
        logger.info(f"[1/3] dws_customer_360: {len(result1)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[1/3] dws_customer_360 查询失败: {e}")

    # Source 2: dws_contact_mapping（联系人映射聚合表，含各 ods 联系人的公司名）
    # 该表无独立行 id 概念（由公司名+手机唯一），record_id 置 None；
    # 候选 id 仅在名称同时存在于 dws_customer_360 时通过 c360_id_map 锚定。
    try:
        t0 = time.time()
        logger.info("[2/3] 查询 dws_contact_mapping...")
        sql2 = text("""
            SELECT DISTINCT customer_name
            FROM dws_contact_mapping
            WHERE customer_name IS NOT NULL AND customer_name != ''
        """)
        result2 = db.execute(sql2).fetchall()
        for (_raw_name,) in result2:
            record_id = None
            company_name = clean_company_symbols(_raw_name)
            if not company_name:
                continue
            src_entry = {"table": "dws_contact_mapping", "record_id": record_id}
            if company_name not in companies:
                companies[company_name] = {
                    "name": company_name,
                    "customer_id": None,
                    "sources": [src_entry],
                }
            else:
                existing_tables = {s["table"] if isinstance(s, dict) else s for s in companies[company_name]["sources"]}
                if "dws_contact_mapping" not in existing_tables:
                    companies[company_name]["sources"].append(src_entry)
        logger.info(f"[2/3] dws_contact_mapping: {len(result2)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[2/3] dws_contact_mapping 查询失败: {e}")

    # Source 3: dws_interaction_detail（互动明细聚合表，含各 ods 互动的公司名）
    try:
        t0 = time.time()
        logger.info("[3/3] 查询 dws_interaction_detail...")
        sql3 = text("""
            SELECT DISTINCT customer_name
            FROM dws_interaction_detail
            WHERE customer_name IS NOT NULL AND customer_name != ''
        """)
        result3 = db.execute(sql3).fetchall()
        for (_raw_name,) in result3:
            record_id = None
            company_name = clean_company_symbols(_raw_name)
            if not company_name:
                continue
            src_entry = {"table": "dws_interaction_detail", "record_id": record_id}
            if company_name not in companies:
                companies[company_name] = {
                    "name": company_name,
                    "customer_id": None,
                    "sources": [src_entry],
                }
            else:
                existing_tables = {s["table"] if isinstance(s, dict) else s for s in companies[company_name]["sources"]}
                if "dws_interaction_detail" not in existing_tables:
                    companies[company_name]["sources"].append(src_entry)
        logger.info(f"[3/3] dws_interaction_detail: {len(result3)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[3/3] dws_interaction_detail 查询失败: {e}")

    # Source 4/5 原 ods_zhique_contact_detail_day / ods_crm_contact_day 已移除：
    # 它们的公司名已被 dws_contact_mapping / dws_interaction_detail 聚合覆盖，不再直接读 ods。

    result = list(companies.values())
    logger.info(f"数据读取完成: 共 {len(result)} 个唯一公司名, 总耗时 {time.time()-total_start:.1f}s")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Generate Review Pairs
# ─────────────────────────────────────────────────────────────────────────────

def _build_c360_name_id_map(db: Session) -> Dict[str, Any]:
    """构建 公司名 -> dws_customer_360.id 映射。

    审核队列的候选 id 必须指向 dws_customer_360 中真实存在的客户档案，
    而不能使用各 ODS 源的行 id（与 360 表 id 空间不同，会导致跳转/展示错位）。
    多个源的同名公司聚合时，只有 dws_customer_360 源才持有真实客户 id。
    """
    try:
        sql = text(
            "SELECT customer_name, id FROM dws_customer_360 "
            "WHERE customer_name IS NOT NULL AND customer_name != ''"
        )
        rows = db.execute(sql).fetchall()
        mp: Dict[str, Any] = {}
        for name, cid in rows:
            if name and cid is not None and name not in mp:
                mp[name] = cid
        logger.info(f"构建 360 名称->id 映射: {len(mp)} 条")
        return mp
    except Exception as e:
        logger.warning(f"构建 360 名称->id 映射失败: {e}")
        return {}


def _build_branch_pairs_by_chunk(
    companies: List[Dict[str, Any]], chunk_size: int
) -> Dict[int, List[Tuple[int, int, float]]]:
    """将「同主体分支机构」配对按锚点（较小索引）所在块分桶，避免跨块重复产出。
    返回 {chunk_index: [(i, j, 1.0), ...]}。
    """
    branch_groups: Dict[str, List[int]] = defaultdict(list)
    for idx, c in enumerate(companies):
        base, tail = _parse_branch(c["name"])
        # 仅当确实带分支后缀、且剥离出有效主体名（长度>=2）才参与聚合
        if tail and base and len(base) >= 2:
            branch_groups[base].append(idx)
    by_chunk: Dict[int, List[Tuple[int, int, float]]] = defaultdict(list)
    for base, idxs in branch_groups.items():
        if len(idxs) >= 2:
            for a in range(len(idxs)):
                for b in range(a + 1, len(idxs)):
                    i, j = idxs[a], idxs[b]
                    anchor = min(i, j)
                    by_chunk[anchor // chunk_size].append((i, j, 1.0))
    return by_chunk


def iter_similar_pair_chunks(
    embeddings: List[np.ndarray],
    names: List[str],
    threshold: float = 0.85,
    chunk_size: int = DEDUP_WRITE_CHUNK,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Iterator[Tuple[int, int, List[Tuple[int, int, float]]]]:
    """分块流式查找相似对：仅建一次索引，按公司块（chunk_size）逐块查询并 yield，
    调用方可每处理完一块即评分+落库提交（检查点），避免一次性在内存生成全部相似对
    再统一写入导致崩溃时全损。

    Yields:
        (chunk_start, chunk_end, pairs) —— pairs 为该块内公司作为锚点产出的相似对
        （每个 pair 仅在其较小索引所在块产出一次，跨块/块内不重复）。
    """
    n = len(embeddings)
    if n < 2:
        return
    dim = len(embeddings[0])
    emb_array = np.array([e.astype(np.float32) for e in embeddings], dtype=np.float32)

    # 精确归一化匹配（全局）按锚点块分桶
    name_to_indices: Dict[str, List[int]] = defaultdict(list)
    for i, name in enumerate(names):
        norm = normalize_company_name(name)
        if norm:
            name_to_indices[norm].append(i)
    exact_by_chunk: Dict[int, List[Tuple[int, int, float]]] = defaultdict(list)
    for normalized, idx_list in name_to_indices.items():
        if len(idx_list) > 1:
            for a in range(len(idx_list)):
                for b in range(a + 1, len(idx_list)):
                    i, j = idx_list[a], idx_list[b]
                    exact_by_chunk[min(i, j) // chunk_size].append((i, j, 0.98))

    k = min(n, FAISS_K_NEAREST_NEIGHBORS)

    if _FAISS_AVAILABLE:
        # FAISS：建一次索引，逐块查询该块向量的近邻
        index = faiss.IndexFlatIP(dim)
        index.add(emb_array)
        for cstart in range(0, n, chunk_size):
            cend = min(cstart + chunk_size, n)
            chunk_pairs = list(exact_by_chunk.get(cstart // chunk_size, []))
            seen = {(i, j) for (i, j, _) in chunk_pairs}
            distances, indices = index.search(emb_array[cstart:cend], k)
            for off in range(cend - cstart):
                i = cstart + off
                for jj in range(k):
                    j = int(indices[off][jj])
                    if j < 0 or j >= n:
                        continue
                    sim = float(distances[off][jj])
                    if sim < threshold:
                        continue
                    if i >= j:
                        continue
                    norm_i = normalize_company_name(names[i])
                    norm_j = normalize_company_name(names[j])
                    if norm_i == norm_j and norm_i:
                        continue
                    key = (i, j)
                    if key in seen:
                        continue
                    seen.add(key)
                    chunk_pairs.append((i, j, sim))
            if progress_callback:
                progress_callback(min(cend, n), n, f"查找相似公司: {min(cend, n)}/{n}")
            yield cstart, cend, chunk_pairs
    else:
        # 暴力：建一次矩阵，逐块切片做向量化点积（仅 n<100 或 FAISS 不可用时走此分支）
        for cstart in range(0, n, chunk_size):
            cend = min(cstart + chunk_size, n)
            chunk_pairs = list(exact_by_chunk.get(cstart // chunk_size, []))
            seen = {(i, j) for (i, j, _) in chunk_pairs}
            sims = emb_array[cstart:cend] @ emb_array.T  # (chunk, n)
            for off in range(cend - cstart):
                i = cstart + off
                row = sims[off]
                for j in range(i + 1, n):
                    sim = float(row[j])
                    if sim < threshold:
                        continue
                    norm_i = normalize_company_name(names[i])
                    norm_j = normalize_company_name(names[j])
                    if norm_i == norm_j and norm_i:
                        continue
                    key = (i, j)
                    if key in seen:
                        continue
                    seen.add(key)
                    chunk_pairs.append((i, j, sim))
            if progress_callback:
                progress_callback(min(cend, n), n, f"查找相似公司: {min(cend, n)}/{n}")
            yield cstart, cend, chunk_pairs


# ──────────────────────────────────────────────────────────────────────────────
# 相似对磁盘缓存（加速 re-run：跳过嵌入加载与 FAISS）
# 相似对由「确定性嵌入 → FAISS 检索」推导，只要公司名集合与关键参数未变即可直接复用，
# 避免每次 re-run 都从 SQLite 加载 ~2.1GB 嵌入向量并重建/检索 FAISS 索引。
# 缓存以「名字列表 + 下标对」紧凑存储（约数十 MB），签名由排序后的公司名集合 + 阈值 +
# k + 维度 + embedding 模型构成，任一项变化都会自动失效重算，保证结果正确。
# ──────────────────────────────────────────────────────────────────────────────
def _embedding_model_id() -> str:
    """返回用于相似对缓存签名的 embedding 标识：真实 API 模型名，或 hash 兜底标记。"""
    from app.config import settings
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL
    if not api_key or not base_url:
        return "hash"
    return f"api:{settings.EMBEDDING_MODEL}"


def _similar_pairs_signature(names: List[str], model_id: str) -> str:
    """基于公司名集合（顺序无关）+ 关键参数计算签名，任一变化都使缓存失效。"""
    h = hashlib.sha256()
    h.update(model_id.encode("utf-8"))
    h.update(b"|")
    h.update(str(EMBEDDING_SIMILARITY_THRESHOLD).encode("utf-8"))
    h.update(b"|")
    h.update(str(FAISS_K_NEAREST_NEIGHBORS).encode("utf-8"))
    h.update(b"|")
    h.update(str(EMBEDDING_DIM).encode("utf-8"))
    h.update(b"|")
    # 公司名集合决定嵌入/相似对；用排序后拼接做内容哈希（顺序无关，仅集合相关）
    h.update("".join(sorted(names)).encode("utf-8"))
    return h.hexdigest()


def _similar_pairs_cache_path() -> Path:
    return _PROJECT_ROOT / "data" / "dedup_similar_pairs.cache"


def _merge_exact_pairs_into(
    chunks_map: Dict[int, List[Tuple[int, int, float]]],
    names: List[str],
    chunk_size: int,
) -> None:
    """把规范化后完全相同的公司名直接成对（确定性，不走 FAISS），并入 chunk 分桶。

    与 iter_similar_pair_chunks 的 exact_by_chunk 逻辑保持一致：每个 pair 仅在其
    较小索引所在块产出一次。
    """
    name_to_indices: Dict[str, List[int]] = defaultdict(list)
    for i, name in enumerate(names):
        norm = normalize_company_name(name)
        if norm:
            name_to_indices[norm].append(i)
    for _norm, idx_list in name_to_indices.items():
        if len(idx_list) > 1:
            for a in range(len(idx_list)):
                for b in range(a + 1, len(idx_list)):
                    i, j = idx_list[a], idx_list[b]
                    chunks_map[min(i, j) // chunk_size].append((i, j, 0.98))


def _save_similar_pairs_cache(
    names: List[str],
    model_id: str,
    all_chunks: List[Tuple[int, int, List[Tuple[int, int, float]]]],
) -> None:
    """把相似对按「名字列表 + 下标对」落盘，供 re-run 直接复用。

    存储下标（相对本次 names 列表）而非公司名，体积远小于逐对存名字；
    加载时通过签名校验保证 names 集合一致，再按下标翻译回当前运行的下标。
    """
    try:
        cache_dir = _PROJECT_ROOT / "data"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = _similar_pairs_cache_path()
        idx_pairs: List[Tuple[int, int, float]] = []
        for _cstart, _cend, pairs in all_chunks:
            for i, j, sim in pairs:
                idx_pairs.append((int(i), int(j), float(sim)))
        payload = {
            "signature": _similar_pairs_signature(names, model_id),
            "model_id": model_id,
            "names": names,
            "pairs": idx_pairs,
        }
        with open(cache_path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("相似对缓存已写入：%s（%d 对）", cache_path, len(idx_pairs))
    except Exception as e:
        logger.warning("相似对缓存写入失败（忽略，下次 re-run 将重算）：%s", e)


def _load_similar_pairs_cache(
    names: List[str], model_id: str
) -> Optional[List[Tuple[int, int, float]]]:
    """若签名匹配则返回扁平的 (i, j, sim) 相似对列表，否则 None（触发重算）。"""
    try:
        cache_path = _similar_pairs_cache_path()
        if not cache_path.exists():
            return None
        with open(cache_path, "rb") as f:
            payload = pickle.load(f)
        if payload.get("signature") != _similar_pairs_signature(names, model_id):
            logger.info("相似对缓存签名不匹配（公司名集合或参数已变），失效重算")
            return None
        stored_names = payload.get("names") or []
        name_to_idx = {name: idx for idx, name in enumerate(names)}
        idx_pairs = payload.get("pairs", [])
        result: List[Tuple[int, int, float]] = []
        for ia, ib, sim in idx_pairs:
            a = stored_names[ia] if 0 <= ia < len(stored_names) else None
            b = stored_names[ib] if 0 <= ib < len(stored_names) else None
            if a is None or b is None:
                continue
            ii = name_to_idx.get(a)
            jj = name_to_idx.get(b)
            if ii is None or jj is None or ii == jj:
                continue
            i, j = (ii, jj) if ii < jj else (jj, ii)
            result.append((i, j, sim))
        if not result:
            return None
        logger.info(
            "相似对缓存命中：%s（%d 对，跳过嵌入加载与 FAISS）", cache_path, len(result)
        )
        return result
    except Exception as e:
        logger.warning("相似对缓存读取失败（忽略，重新计算）：%s", e)
        return None


def generate_review_pairs(
    incremental: bool = True
) -> Dict[str, Any]:
    """
    生成所有潜在重复对并插入 review_candidate。

    会话策略：读取阶段（Step 1）与写入阶段（Step 4）各自使用独立短生命周期会话，
    中间的嵌入计算 / FAISS / 评分等耗时处理不持有任何数据库连接。否则长耗时处理期间
    连接会被服务端 wait_timeout 回收，导致后续查询报 2013（Lost connection）并
    在会话上堆积 PendingRollbackError。

    Args:
        incremental: 是否使用增量模式（仅处理新增/更新的公司）

    Returns:
        去重运行统计信息
    """
    global _dedup_progress

    # Step 1: 获取公司名称（增量或全量）
    # Step 1: 获取公司名称（增量或全量）
    _set_phase_progress(0, 0.0, extra={
        "completed": 0, "total": 0, "message": "正在从数据库读取公司名称..."})

    # 读取阶段使用独立会话，结束后立即关闭归还连接；
    # 避免「嵌入计算/FAISS」等长耗时非 DB 处理期间长期持有连接被服务端回收（见 2013 报错）。
    with SessionLocal() as read_db:
        if incremental:
            last_time = get_last_dedup_time()
            if last_time:
                companies = fetch_new_or_updated_companies(read_db, since=last_time)
                logger.info(f"增量去重: since={last_time}, 获取 {len(companies)} 家公司")
            else:
                companies = fetch_all_company_names(read_db)
                logger.info(f"首次运行全量去重: {len(companies)} 家公司")
        else:
            companies = fetch_all_company_names(read_db)

        # 构建 公司名 -> dws_customer_360.id 映射，确保审核队列 id 指向真实客户档案
        # （避免直接用各 ODS 源行 id 导致前端跳转/详情与展示公司名错位）。
        c360_id_map = _build_c360_name_id_map(read_db)
    # ← read_db 在此关闭并归还连接；后续长耗时计算期间不再占用任何数据库连接

    # 过滤 & 标准化：
    # (1) 公司名称不能为空，空名称直接过滤掉
    # (2) customer_id 为空的公司，将其 id 设为 "default_id"（允许无真实ID的公司参与去重）
    total_before_filter = len(companies)
    companies_filtered = []
    filtered_empty_name = 0
    filtered_short_name = 0
    set_default_id_count = 0
    for c in companies:
        name = (c.get("name") or "").strip()
        if not name:
            filtered_empty_name += 1
            continue
        # 排除过短的公司名（如"北京""上海"等碎片），这些名称信息量太少，容易误匹配
        if len(name) < MIN_COMPANY_NAME_LENGTH:
            filtered_short_name += 1
            continue
        c["name"] = name
        if c.get("customer_id") is None:
            c["customer_id"] = "default_id"
            set_default_id_count += 1
        companies_filtered.append(c)
    companies = companies_filtered
    names = [c["name"] for c in companies]
    if filtered_empty_name > 0:
        logger.info(f"过滤掉 {filtered_empty_name} 个名称为空的公司")
    if filtered_short_name > 0:
        logger.info(f"过滤掉 {filtered_short_name} 个名称过短的公司（少于 {MIN_COMPANY_NAME_LENGTH} 个字符）")
    if set_default_id_count > 0:
        logger.info(f"{set_default_id_count} 个公司缺少 customer_id，已设为 default_id")
    _set_phase_progress(0, 1.0, extra={
        "completed": len(companies),
        "total": total_before_filter,
        "message": f"已获取 {total_before_filter} 家公司（过滤空名称 {filtered_empty_name}，短名称 {filtered_short_name}，default_id {set_default_id_count}）"
    })
    
    # 测试模式：限制处理的公司数量（通过 .env 中的 DEDUP_TEST_MODE_MAX_COMPANIES 配置，0=不限制）
    from app.config import settings
    max_companies = getattr(settings, 'DEDUP_TEST_MODE_MAX_COMPANIES', 0)
    if max_companies > 0 and len(names) > max_companies:
        logger.info(f"测试模式：限制处理前 {max_companies} 个公司（原始: {len(names)} 个）")
        companies = companies[:max_companies]
        names = names[:max_companies]
        _dedup_progress["details"]["message"] = f"测试模式：已限制为 {max_companies} 家公司"

    if len(names) < 2:
        return {
            "total_companies": len(names),
            "pairs_found": 0,
            "auto_merged": 0,
            "need_review": 0,
            "new_pairs_found": 0,
        }

    # Step 2: Compute embeddings
    _set_phase_progress(1, 0.0, extra={
        "completed": 0, "total": len(names), "workers": EMBEDDING_MAX_WORKERS,
        "message": f"正在计算嵌入向量... (0/{len(names)})"})

    def _embedding_progress_callback(completed: int, total: int, message: Optional[str] = None):
        """Embedding 计算进度回调（阶段1内部完成度驱动全局进度，单调不减）。"""
        # workers 反映并行线程数（仅配置了真实 Embedding API 时生效；hash 兜底为串行）
        _set_phase_progress(1, (completed / total) if total else 1.0, extra={
            "completed": completed,
            "total": total,
            "workers": EMBEDDING_MAX_WORKERS,
            "message": message or f"正在计算嵌入向量... ({completed}/{total})",
        })
    
    # ── Step 2 + Step 3：嵌入向量 + FAISS 相似对 ──
    # 加速 re-run：相似对由「确定性嵌入 → FAISS 检索」推导，只要公司名集合与关键参数未变
    # 即可直接复用磁盘缓存，跳过 ~2.1GB 嵌入加载与 FAISS 构建/检索（这两步是 re-run 最重的
    # 负担）。签名基于排序后的公司名集合 + 阈值 + k + 维度 + embedding 模型，任一项变化都会
    # 自动失效重算，保证结果正确。
    model_id = _embedding_model_id()
    cached_pairs = _load_similar_pairs_cache(names, model_id)
    embeddings = None
    if cached_pairs is not None:
        _set_phase_progress(1, 1.0, extra={
            "completed": len(names), "total": len(names),
            "message": "相似对缓存命中，跳过嵌入计算"})
        _set_phase_progress(2, 1.0, extra={
            "completed": len(names), "total": len(names),
            "message": "相似对缓存命中，跳过 FAISS 检索"})
        # 把扁平的 (i, j, sim) 按 min 下标分桶回 chunk 结构（与 iter_similar_pair_chunks
        # 输出一致），并补回规范相同的精确对（纯名称推导、成本低，无需缓存）。
        chunks_map: Dict[int, List[Tuple[int, int, float]]] = defaultdict(list)
        for i, j, sim in cached_pairs:
            chunks_map[min(i, j) // DEDUP_WRITE_CHUNK].append((i, j, sim))
        _merge_exact_pairs_into(chunks_map, names, DEDUP_WRITE_CHUNK)
        all_chunks = [
            (c * DEDUP_WRITE_CHUNK, min((c + 1) * DEDUP_WRITE_CHUNK, len(names)), chunks_map.get(c, []))
            for c in range((len(names) + DEDUP_WRITE_CHUNK - 1) // DEDUP_WRITE_CHUNK)
        ]
        chunk_iter = iter(all_chunks)
    else:
        # Step 2: 计算嵌入向量（分批、并发、带缓存）
        embeddings = compute_embeddings_batch(names, progress_callback=_embedding_progress_callback)

        # Step 3: 分块流式查找相似对（仅建一次索引，逐块产出）
        _set_phase_progress(2, 0.0, extra={
            "completed": 0, "total": len(names),
            "message": f"正在查找相似公司对... (输入: {len(names)} 个公司)"})

        def _similar_pairs_progress_callback(completed: int, total: int, message: str):
            """相似对查找进度回调（阶段2内部完成度驱动全局进度，单调不减）。"""
            _set_phase_progress(2, (completed / total) if total else 1.0, extra={
                "completed": completed,
                "total": total,
                "message": message,
            })

        chunk_iter = iter_similar_pair_chunks(
            embeddings, names, threshold=EMBEDDING_SIMILARITY_THRESHOLD,
            chunk_size=DEDUP_WRITE_CHUNK, progress_callback=_similar_pairs_progress_callback,
        )
        # 物化并落盘缓存（供下次 re-run 直接复用），随后释放 2.1GB 嵌入以降内存压力
        all_chunks = list(chunk_iter)
        _save_similar_pairs_cache(names, model_id, all_chunks)
        chunk_iter = iter(all_chunks)
        embeddings = None

    branch_by_chunk = _build_branch_pairs_by_chunk(companies, DEDUP_WRITE_CHUNK)
    total_company_chunks = (len(names) + DEDUP_WRITE_CHUNK - 1) // DEDUP_WRITE_CHUNK
    logger.info(
        "分块流式去重：%d 个公司，按 %d/块分为 %d 块，逐块查找+评分+落库",
        len(names), DEDUP_WRITE_CHUNK, total_company_chunks,
    )

    # Step 4: 计算证据评分并分批写入审核队列
    # 关键修复（PendingRollbackError 根因）：
    # 当相似对达到百万级（本次 230 万+）时，若所有写入放在「单一会话 + 单一事务」里，
    # 绝大多数低分对（final_score<=阈值）只做 Python 计算、完全不触达数据库，导致被 checkout
    # 的连接长时间空闲，被服务端 wait_timeout 静默回收；随后首个需写入的对执行 write_db.execute
    # 时连接已死 → 2013，会话进入 invalid 状态，后续每条写入都抛 PendingRollbackError。
    # 改为：先一次性完成「批量证据评分 + 已存在 pair 集合」（独立短会话，立即归还连接），
    # 随后按 BATCH_SIZE 分批写入，每批使用独立短生命周期会话并立即提交——
    # 连接永不长期空闲，单批连接失活也只回滚该批并用新会话重试，不影响已提交数据。
    # Step 4: 评分与写入队列（分块）。先标记进入阶段3，并准备块级上下文供证据回调使用。
    _chunk_ctx: Dict[str, int] = {"idx": 0, "start": 0, "end": 0}
    _set_phase_progress(3, 0.0, extra={
        "completed": 0, "total": len(names), "message": "准备分块评分与写入队列..."})

    # 证据评分回调：仅反映「当前块内」子进度（details），全局进度由块末检查点单调推进，
    # 彻底消除“块1 证据→写库 80%+，块2 证据又从 45% 起”的回退现象。
    def _evidence_progress_callback(completed: int, total: int, message: str):
        """证据评分进度回调：块内子进度，不直接回写全局进度。"""
        frac = (completed / total) if total else 0.0
        base = _chunk_ctx["start"]
        span = (_chunk_ctx["end"] - _chunk_ctx["start"]) or 1
        # 证据评分占本块进度前半段（写库占后半段，由块末检查点推进）
        local = (base + 0.5 * frac * span) / max(1, len(names))
        _set_phase_progress(3, local, extra={
            "completed": int(base + frac * span),
            "total": len(names),
            "chunk_index": _chunk_ctx["idx"] + 1,
            "chunk_total": total_company_chunks,
            "chunk_phase": "证据评分",
            "chunk_completed": completed,
            "chunk_total_pairs": total,
            "message": message or f"第 {_chunk_ctx['idx'] + 1}/{total_company_chunks} 块：证据评分中... ({completed}/{total})",
        })

    # 已存在 pair 集合：批量查询，独立短会话，结束立即归还连接。
    # 注：证据评分不再全局一次性计算，改为逐块（见下方分块写入循环）独立会话评分，
    # 避免一次性在内存生成全部对的证据、也避免长时间持有连接空闲。
    with SessionLocal() as prep_db:
        # 检查已存在候选对：阶段3内的瞬时子步骤，仅更新 details，不回写全局进度
        _set_phase_progress(3, 0.0, extra={
            "completed": 0, "total": len(names),
            "message": "检查已存在候选对，准备分块评分与写入..."})

        # 批量查询已存在的 pair，避免循环中逐条查询
        existing_pairs: set = set()
        try:
            existing_sql = text("""
                SELECT candidate_a_name, candidate_b_name
                FROM review_candidate
            """)
            existing_rows = prep_db.execute(existing_sql).fetchall()

            for row in existing_rows:
                name_a, name_b = row[0], row[1]
                # 统一存储为 (较小名称, 较大名称)，便于查找
                pair_key = (name_a, name_b) if name_a <= name_b else (name_b, name_a)
                existing_pairs.add(pair_key)

            logger.info(f"Found {len(existing_pairs)} existing pairs in review_candidate")
            _dedup_progress["details"] = {"step_name": "检查已存在的pair", "completed": len(existing_pairs), "total": len(existing_pairs), "message": f"找到 {len(existing_pairs)} 个已存在的pair"}
        except Exception as e:
            logger.warning(f"Failed to fetch existing pairs: {e}")
            existing_pairs = set()
            _dedup_progress["details"] = {"step_name": "检查已存在的pair", "completed": 0, "total": 0, "message": "检查失败，继续执行"}

    # 清理历史非法候选：任一侧 id 为 default_id（dws_customer_360 中无真实档案、仅来自 ODS 源的
    # 公司）的队列行属于非法数据，直接删除，确保审核队列只含可定位到 dws 档案的候选。
    try:
        with SessionLocal() as clean_db:
            clean_db.execute(
                text("DELETE FROM review_candidate WHERE candidate_a_id = :did OR candidate_b_id = :did"),
                {"did": "default_id"},
            )
            clean_db.commit()
        logger.info("已清理 review_candidate 中 default_id 非法候选")
    except Exception as e:
        logger.warning(f"清理 default_id 非法候选失败（不影响本次去重）: {e}")

    # 写入阶段：分批提交，每批独立会话 + 连接失活重试（单批失败不影响已提交数据）。
    BATCH_SIZE = 1000
    MAX_BATCH_RETRY = 3
    new_pairs_count = 0
    auto_merged_count = 0
    need_review_count = 0

    # 诊断：收集评分数据用于统计分析
    all_rule_scores = []
    all_evidence_scores = []
    all_llm_scores = []
    all_final_scores = []

    insert_sql = text("""
        INSERT INTO review_candidate
        (review_type, candidate_a_id, candidate_a_name,
         candidate_b_id, candidate_b_name,
         match_score, rule_score, evidence_score, llm_score,
         evidence, status)
        VALUES (:type, :a_id, :a_name,
                :b_id, :b_name,
                :match, :rule_score, :evidence_score, :llm_score,
                :evidence_json, :status)
    """)

    def _write_batch(batch: List[Tuple[int, int, float]], batch_evidence: Dict) -> None:
        """对一批相似对评分+落库（每批独立会话+提交，单批失败不影响已提交）。

        通过 nonlocal 更新外层的计数器与全局统计集合，保持与原分批写入逻辑一致。
        """
        nonlocal new_pairs_count, auto_merged_count, need_review_count, existing_pairs
        nonlocal all_rule_scores, all_evidence_scores, all_llm_scores, all_final_scores
        batch_inserted_keys: list = []
        for attempt in range(MAX_BATCH_RETRY):
            try:
                with SessionLocal() as wb:
                    # 本批的诊断数据，提交成功后才并入全局统计，避免重试重复计数
                    _b_rule, _b_ev, _b_llm, _b_final = [], [], [], []
                    for (idx_a, idx_b, similarity) in batch:
                        company_a = companies[idx_a]
                        company_b = companies[idx_b]

                        # 计算规则评分
                        rule_score = calculate_rule_score(company_a["name"], company_b["name"])

                        # 从批量结果获取证据评分
                        key = (company_a["name"], company_b["name"])
                        rev_key = (company_b["name"], company_a["name"])
                        if key in batch_evidence:
                            evidence_score, shared_count, shared_details = batch_evidence[key]
                        elif rev_key in batch_evidence:
                            evidence_score, shared_count, shared_details = batch_evidence[rev_key]
                        else:
                            evidence_score, shared_count, shared_details = 0.0, 0, []

                        # LLM 判断：批量写入阶段不调用大模型（性能瓶颈），
                        # 使用规则分+证据分的代理值作为 LLM 分，后续人工审核时可再触发真实 LLM 分析。
                        llm_score_100 = round(rule_score * 0.5 + evidence_score * 0.5, 2)
                        explanation = ""

                        # Final score uses: rule 30%, evidence 30%, llm 40%
                        final_score = calculate_final_score(
                            rule_score, evidence_score, similarity, llm_score_100
                        )

                        # 分支机构同公司规则：同名主体（去掉分公司/办事处等后缀）的多个分支机构
                        # 视为同一公司，直接强制自动合并，不再依赖多维评分阈值。
                        branch_base = _branch_canonical(company_a["name"], company_b["name"])
                        if branch_base:
                            final_score = 100.0
                            rule_score = 100.0
                            evidence_score = 0.0
                            llm_score_100 = 100.0
                            explanation = f"同一公司分支机构，归并至总部主体：{branch_base}"

                        _b_rule.append(rule_score)
                        _b_ev.append(evidence_score)
                        _b_llm.append(llm_score_100)
                        _b_final.append(final_score)

                        # Determine status (thresholds per config)
                        if final_score > AUTO_MERGE_THRESHOLD:
                            status = "auto_merged"
                            auto_merged_count += 1
                        elif final_score > NEED_REVIEW_THRESHOLD:
                            status = "need_review"
                            need_review_count += 1
                        else:
                            # Below threshold — skip insertion entirely
                            continue

                        # Check if pair already exists in review_candidate (使用内存集合，避免数据库查询)
                        a_name = company_a["name"]
                        b_name = company_b["name"]
                        pair_key = (a_name, b_name) if a_name <= b_name else (b_name, a_name)

                        if pair_key in existing_pairs:
                            continue

                        # 仅保留两侧都存在于 dws_customer_360（有真实档案 id）的候选：
                        # 任一侧仅来自 ODS 源、dws 中无对应档案（id 回退为 default_id）属非法数据，跳过。
                        a_id = c360_id_map.get(company_a["name"], company_a.get("customer_id"))
                        b_id = c360_id_map.get(company_b["name"], company_b.get("customer_id"))
                        if a_id == "default_id" or a_id is None or b_id == "default_id" or b_id is None:
                            continue

                        # Prepare evidence JSON (extended structure)
                        evidence = {
                            "rule_score": rule_score,
                            "evidence_score": evidence_score,
                            "llm_score": llm_score_100,
                            "embedding_similarity": round(similarity, 4),
                            "sources_a": company_a["sources"],
                            "sources_b": company_b["sources"],
                            "shared_contacts_count": shared_count,
                            "shared_contact_details": shared_details,
                            "llm_explanation": explanation,
                            "branch_canonical": branch_base,
                        }

                        wb.execute(insert_sql, {
                            "type": "company_merge",
                            # 候选 id 必须绑定 dws_customer_360 的真实客户 id（而非 ODS 源行 id），
                            # 否则前端跳转/详情会与展示的公司名错位。上面已过滤 default_id 非法数据。
                            "a_id": str(a_id),
                            "a_name": company_a["name"],
                            "b_id": str(b_id),
                            "b_name": company_b["name"],
                            "match": final_score,
                            "rule_score": rule_score,
                            "evidence_score": evidence_score,
                            "llm_score": llm_score_100,
                            "evidence_json": json.dumps(evidence, ensure_ascii=False),
                            "status": status,
                        })
                        batch_inserted_keys.append(pair_key)
                        new_pairs_count += 1
                    wb.commit()
                # 仅本批成功提交后才并入 existing_pairs 与全局统计，
                # 避免「未提交却误判已存在」导致的静默丢数据。
                existing_pairs.update(batch_inserted_keys)
                all_rule_scores.extend(_b_rule)
                all_evidence_scores.extend(_b_ev)
                all_llm_scores.extend(_b_llm)
                all_final_scores.extend(_b_final)
                break
            except (OperationalError, PendingRollbackError) as _e:
                # 连接失活：当前批次未提交的内容不并入 existing_pairs，重试时重新插入，保证不丢数据。
                logger.warning(
                    "审核对写入批次连接失活，回滚并用新会话重试（第 %d 次）: %s",
                    attempt + 1, _e,
                )
                if attempt == MAX_BATCH_RETRY - 1:
                    logger.error(
                        "审核对写入批次重试 %d 次仍失败，跳过该批次（损失 %d 对）",
                        MAX_BATCH_RETRY, len(batch),
                    )

    # 分块流式写入：每处理完一块公司即评分+落库提交（检查点），崩溃仅丢当前块。
    # 块内仍按 BATCH_SIZE 对分批评分+写入（每批独立会话+提交，单批失败不影响已提交）。
    total_pairs_found = 0
    processed_companies = 0
    for chunk_idx, (cstart, cend, chunk_similar_pairs) in enumerate(chunk_iter):
        # 更新块级上下文，供证据评分回调捕获当前块（保证全局进度单调不减）
        _chunk_ctx["idx"] = chunk_idx
        _chunk_ctx["start"] = cstart
        _chunk_ctx["end"] = cend

        # 合并该块的分支同公司对（按锚点块分桶，避免跨块重复）
        chunk_pairs = list(chunk_similar_pairs)
        for (i, j, sim) in branch_by_chunk.get(cstart // DEDUP_WRITE_CHUNK, []):
            chunk_pairs.append((i, j, sim))
        total_pairs_found += len(chunk_pairs)

        # 预过滤：已存在于 review_candidate 的候选对直接跳过，避免对其重复执行昂贵的
        # 证据评分（DB 批量查询）与规则/综合评分。existing_pairs 在写入成功后才并入，
        # 因此不会误判「未提交的对」为已存在，保证不丢数据。
        # 关键修复：原逻辑把 existing_pairs 检查放在 _write_batch 内层、且证据评分在过滤前
        # 全量执行，导致每次 re-run 都要对全部（含已存在的两三百万）候选对重查 DB、重算分，
        # 这正是「每次都全量、很慢」的根因。挪到此处可让 re-run 只对真正新增的对做昂贵计算。
        new_chunk_pairs: list = []
        skipped_existing = 0
        for (i, j, sim) in chunk_pairs:
            a_name = companies[i]["name"]
            b_name = companies[j]["name"]
            pair_key = (a_name, b_name) if a_name <= b_name else (b_name, a_name)
            if pair_key in existing_pairs:
                skipped_existing += 1
                continue
            new_chunk_pairs.append((i, j, sim))
        chunk_pairs = new_chunk_pairs

        # 证据评分（按块，独立会话，结束即归还连接）；仅针对本块新发现的对，已存在的跳过
        pair_names = [(companies[i]["name"], companies[j]["name"]) for (i, j, _s) in chunk_pairs]
        with SessionLocal() as ev_db:
            batch_evidence = (
                batch_calculate_evidence_scores(pair_names, ev_db, progress_callback=_evidence_progress_callback)
                if pair_names else {}
            )

        # 块内按 BATCH_SIZE 分批评分+落库
        chunk_batches = (len(chunk_pairs) + BATCH_SIZE - 1) // BATCH_SIZE
        for batch_idx in range(chunk_batches):
            batch = chunk_pairs[batch_idx * BATCH_SIZE:(batch_idx + 1) * BATCH_SIZE]
            _write_batch(batch, batch_evidence)

        # 检查点进度：按已处理公司数单调推进（核心修复：跨块不再回退）
        processed_companies = min(cend, len(names))
        _set_phase_progress(3, processed_companies / len(names), extra={
            "completed": processed_companies,
            "total": len(names),
            "chunk_index": chunk_idx + 1,
            "chunk_total": total_company_chunks,
            "chunk_phase": "写入队列",
            "chunk_completed": len(chunk_pairs),
            "chunk_total_pairs": len(chunk_pairs),
            "message": (
                f"第 {chunk_idx + 1}/{total_company_chunks} 块：评分+写入完成 "
                f"（本块新增 {len(chunk_pairs)} 对，跳过已存在 {skipped_existing} 对，"
                f"累计处理公司 {processed_companies}/{len(names)}）"
            ),
        })

    # 仅记录关键统计信息
    if all_final_scores:
        logger.info(f"评分统计: 共 {len(all_final_scores)} 个相似对, "
                    f"综合评分 avg={sum(all_final_scores)/len(all_final_scores):.2f}, "
                    f"自动合并: {auto_merged_count}, 待审核: {need_review_count}")

    # 候选对评分与写入队列已完成（整体进度到达 99%，「评分与写入队列」步骤完成）。
    # 注意：严禁在此处提前把阶段 4（完成）置为 100%——自动合并与落库尚未执行，
    # 否则前端会误判为「已完成」并提前停止轮询，且用户会在合并真正落库前查看数据，
    # 误以为自动合并未生效。阶段 4 的 100% 由 run_deduplication_background 在所有
    # 合并落库完成后统一上报。
    _set_phase_progress(3, 1.0, extra={
        "completed": total_pairs_found,
        "total": total_pairs_found,
        "message": f"评分与写入队列完成（共 {total_pairs_found} 个相似对，"
                   f"新增 {new_pairs_count} 个待审核对），正在执行自动合并与落库...",
    })

    return {
        "total_companies": len(companies),
        "pairs_found": total_pairs_found,
        "new_pairs_found": new_pairs_count,
        "auto_merged": auto_merged_count,
        "need_review": need_review_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-merge High Confidence Pairs
# ─────────────────────────────────────────────────────────────────────────────

def auto_merge_high_confidence(db: Session, threshold: float = HIGH_CONFIDENCE_MERGE_THRESHOLD) -> int:
    """
    Auto-merge pairs with score above threshold.

    Args:
        db: Database session
        threshold: Minimum score for auto-merge

    Returns:
        Number of pairs auto-merged
    """
    update_sql = text("""
        UPDATE review_candidate
        SET status = 'auto_merged',
            reviewed_by = 'system',
            reviewed_at = NOW()
        WHERE status IN ('pending', 'need_review')
          AND match_score >= :threshold
          AND review_type = 'company_merge'
    """)

    result = db.execute(update_sql, {"threshold": threshold})
    db.commit()

    count = result.rowcount
    logger.info(f"Auto-merged {count} high-confidence pairs")
    return count


# ─────────────────────────────────────────────────────────────────────────────
# 分支机构同公司识别
# ─────────────────────────────────────────────────────────────────────────────
# 同一法人的"总部/母公司"与各地"分公司、办事处、代表处"等应视为同一家公司，
# 例如「锐捷网络北京分公司」与「锐捷网络上海分公司」实为同一主体，需自动合并。
# 注意：与控股但独立注册的公司（如「星网锐捷」与「锐捷网络」）区分，后者 base 不同不合并。

# 分支类型词（构成"分支机构"后缀的核心词）
_BRANCH_TAIL_WORDS = (
    "分公司|分厂|子公司|办事处|代表处|营销中心|销售中心|经营部|营业部|"
    "项目部|分理处|支公司|分店|门市部|门店|服务部|维修点"
)

# 主体(懒) + 可选第N + 分支词（必须位于末尾）。
# 注意：地理限定（如「北京」）不单独成组，而是被吸收进 base，随后由 _strip_leading_geo
# 按地理词表/省市区县后缀剥离，避免正则贪心把公司主体名吞入地理段。
_BRANCH_PARSE_RE = re.compile(
    r"^(?P<base>.+?)"                                   # 总部/母公司主体（懒匹配）
    r"(?P<ord>第[一二三四五六七八九十百零0-9]+)?"         # 序号（第N，可选，先于分支词）
    r"(?P<tail>" + _BRANCH_TAIL_WORDS + r")$"           # 分支类型词（必须结尾）
)

# 括号括起来的地理，如「锐捷网络（北京）」「锐捷网络(上海)」
_PAREN_GEO_RE = re.compile(r"^(?P<base>.+?)\s*[（(]([一-龥]{1,12})[)）]\s*$")

# 分隔符 + 地理，如「锐捷网络-北京」「锐捷网络—上海」「锐捷网络/华南」
_SEP_GEO_RE = re.compile(r"^(?P<base>.+?)\s*[-—–·/]\s*([一-鿿]{1,12})$")

# 常见省级行政区 + 主要城市（用于剥离分支前的地理限定，得到干净的总部主体名）。
# 非穷举，但覆盖绝大多数分支机构命名；未覆盖的小地名回退为不剥离（仍按截断 base 判等）。
_BRANCH_GEO_TOKENS = {
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏",
    "宁夏", "新疆", "香港", "澳门",
    "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州", "青岛", "沈阳",
    "大连", "厦门", "宁波", "无锡", "福州", "济南", "郑州", "长沙", "哈尔滨", "长春",
    "石家庄", "合肥", "南昌", "昆明", "太原", "南宁", "贵阳", "兰州", "海口", "银川",
    "西宁", "呼和浩特", "乌鲁木齐", "拉萨", "常州", "唐山", "徐州", "潍坊", "烟台",
    "南通", "绍兴", "泉州", "东莞", "佛山", "珠海", "中山", "惠州", "嘉兴", "金华",
    "台州", "温州", "临沂", "洛阳", "襄阳", "宜昌", "株洲", "湘潭", "汕头", "保定",
    "廊坊", "威海", "淄博", "鞍山", "芜湖", "扬州", "盐城", "泰州", "镇江", "九江",
    "赣州", "嘉兴", "保定", "湛江", "江门", "汕头", "揭阳", "潮州", "肇庆", "茂名",
}

# 地理后缀字（带此类字结尾的尾词整体视为地理限定）
_BRANCH_GEO_SUFFIXES = ("省", "市", "区", "县", "自治区", "特区", "州", "盟")


def _strip_leading_geo(base: str) -> str:
    """剥离 base 末尾被吸收进来的地理限定，得到干净的总部主体名。

    例：「锐捷网络北京」->「锐捷网络」、「华为技术有限公司深圳市」->「华为技术有限公司」。
    循环剥离以支持「XX省YY市」等多级行政区划。
    """
    if not base:
        return base
    stripped = base
    changed = True
    while changed:
        changed = False
        for suf in _BRANCH_GEO_SUFFIXES:
            if stripped.endswith(suf):
                idx = stripped.rfind(suf)
                stripped = stripped[:idx]
                changed = True
                break
        if changed:
            continue
        for tok in _BRANCH_GEO_TOKENS:
            if stripped.endswith(tok):
                stripped = stripped[: -len(tok)]
                changed = True
                break
    return stripped.strip()


def _parse_branch(name: str) -> Tuple[str, Optional[str]]:
    """解析公司名，返回 (总部主体名, 分支限定符)。无分支特征时返回 (原名, None)。

    基于原始名解析（不调用 normalize_company_name，因其会剥离'公司'等后缀破坏分支词）。
    """
    if not name or not isinstance(name, str):
        return name, None
    raw = name.strip()
    if not raw:
        return name, None
    m = _BRANCH_PARSE_RE.match(raw)
    if m and m.group("tail"):
        base = _strip_leading_geo(m.group("base").strip())
        return base, m.group("tail")
    m = _PAREN_GEO_RE.match(raw)
    if m:
        return m.group("base").strip(), "（" + m.group(2) + "）"
    m = _SEP_GEO_RE.match(raw)
    if m:
        return m.group("base").strip(), m.group(2)
    return raw, None


def _branch_canonical(name_a: str, name_b: str) -> Optional[str]:
    """判断两个公司名是否为同一公司的"总部/母公司 + 分支机构"关系。

    返回总部主体名（应合并到的 canonical），非同一公司返回 None。覆盖两类：
    （1）两者都是分支机构且去掉分支后缀后的主体名相同（如「锐捷网络北京分公司」与
         「锐捷网络上海分公司」）；
    （2）一个是总部/母公司（无分支后缀），另一个是它的分支机构（如「锐捷网络」与
         「锐捷网络北京分公司」）。
    注意：与控股但独立注册的公司（如「星网锐捷」与「锐捷网络」）区分，后者 base 不同不合并。
    """
    base_a, tail_a = _parse_branch(name_a)
    base_b, tail_b = _parse_branch(name_b)
    if not base_a or not base_b:
        return None
    # 情况（1）：两分支主体相同
    if base_a == base_b and name_a != name_b and (tail_a or tail_b):
        return base_a
    # 情况（2）：一为总部、一为其分支
    if not tail_a and base_b == name_a:
        return base_b
    if not tail_b and base_a == name_b:
        return base_a
    return None


def _resolve_canonical_base(db: Session, base: str) -> str:
    """将分支机构归并目标解析为 360 中已存在的更完整注册主体名（如『锐捷网络股份有限公司』）。

    优先精确匹配；否则取 360 中以该主体开头、且最完整的注册名（最长），避免归并到过短别名。
    """
    try:
        row = db.execute(
            text("SELECT customer_name FROM dws_customer_360 WHERE customer_name = :base"),
            {"base": base},
        ).fetchone()
        if row and row[0]:
            return row[0]
        row = db.execute(
            text(
                "SELECT customer_name FROM dws_customer_360 "
                "WHERE customer_name LIKE CONCAT(:base, '%') "
                "ORDER BY CHAR_LENGTH(customer_name) DESC LIMIT 1"
            ),
            {"base": base},
        ).fetchone()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.warning(f"解析总部主体名失败，回退原始主体名: {e}")
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 公司记录合并
# ─────────────────────────────────────────────────────────────────────────────

def merge_customer_records(
    review_item: Dict[str, Any],
    db: Session
) -> Dict[str, Any]:
    """执行两家公司的实际合并操作（基于 dws 四张聚合表，不再直接改 ods）。

    合并策略：
    1. 确定主公司（优先保留在 dws_customer_360 有记录的一方）。
    2. 把从公司的 dws_contact_360 联系人（仅含 customer_id）改挂到主公司 id。
    3. 把从公司的公司名在 dws_customer_360 / dws_contact_mapping / dws_interaction_detail
       中重命名为总（主）公司名（处理唯一键冲突）。

    Args:
        review_item: 审核项记录（来自 review_candidate，含 candidate_a/b_name 与 candidate_a/b_id）
        db: 数据库会话

    Returns:
        合并结果摘要
    """
    name_a = review_item.get("candidate_a_name") or review_item.get("candidate_a", "")
    name_b = review_item.get("candidate_b_name") or review_item.get("candidate_b", "")

    if not name_a or not name_b:
        raise ValueError("候选公司名称为空，无法合并")

    id_a = review_item.get("candidate_a_id")
    id_b = review_item.get("candidate_b_id")
    merge_stats: Dict[str, Any] = {}

    # 分支机构同公司：两个名称去掉分支后缀后主体相同，直接归并到总部/母公司主体，
    # 两个分公司都改为总部主体名（避免留一个未改名、与总部并列成为重复主体）。
    branch_base = _branch_canonical(name_a, name_b)
    if branch_base:
        canonical = _resolve_canonical_base(db, branch_base)
        logger.info(f"合并(分支机构): {name_a} / {name_b} -> 总部主体 {canonical}")
        # 总部主体的 dws_customer_360 id：优先用总部行，否则回退到一个分支 id
        canonical_id = _resolve_canonical_base_id(db, canonical, id_a, id_b)
        if canonical in (name_a, name_b):
            sources = [(name_b if canonical == name_a else name_a,
                        id_b if canonical == name_a else id_a)]
        else:
            sources = [(name_a, id_a), (name_b, id_b)]
        for src_name, src_id in sources:
            _merge_one_source(src_name, src_id, canonical, canonical_id, db, merge_stats)
        return {
            "success": True,
            "primary_company": canonical,
            "secondary_company": f"{name_a}|{name_b}",
            "updated_records": merge_stats,
            "branch_merge": True,
        }

    # 1. 确定主公司：在 dws_customer_360 中有记录的一方优先
    primary_name, secondary_name = _determine_primary_company(name_a, name_b, db)
    primary_id = id_a if primary_name == name_a else id_b
    secondary_id = id_b if primary_name == name_a else id_a
    logger.info(f"合并: 主公司={primary_name}, 从公司={secondary_name}")

    _merge_one_source(secondary_name, secondary_id, primary_name, primary_id, db, merge_stats)

    return {
        "success": True,
        "primary_company": primary_name,
        "secondary_company": secondary_name,
        "updated_records": merge_stats,
    }


def _determine_primary_company(
    name_a: str, name_b: str, db: Session
) -> Tuple[str, str]:
    """
    确定合并中的主公司。

    优先级规则：
    1. 在 dws_customer_360 中有记录的一方优先
    2. 名称更短的一方优先（更可能是规范化名称）
    """
    check_sql = text("""
        SELECT customer_name FROM dws_customer_360
        WHERE customer_name LIKE :name
        LIMIT 1
    """)
    a_in_360 = db.execute(check_sql, {"name": f"%{name_a}%"}).scalar()
    b_in_360 = db.execute(check_sql, {"name": f"%{name_b}%"}).scalar()

    if a_in_360 and not b_in_360:
        return name_a, name_b
    if b_in_360 and not a_in_360:
        return name_b, name_a

    # 都（不）在 360 中：名称更短的一方作为主公司
    if len(name_a) <= len(name_b):
        return name_a, name_b
    return name_b, name_a


def _resolve_canonical_base_id(
    db: Session, canonical_name: str, id_a: Any, id_b: Any
) -> Any:
    """解析总部主体的 dws_customer_360 id；若不存在则回退到传入的分支 id。"""
    try:
        row = db.execute(
            text("SELECT id FROM dws_customer_360 WHERE customer_name = :name LIMIT 1"),
            {"name": canonical_name},
        ).scalar()
        if row is not None:
            return row
    except Exception as e:
        logger.warning(f"解析总部主体 id 失败，回退分支 id: {e}")
    return id_a or id_b


def _relink_contact_360(
    secondary_id: Any, primary_id: Any, db: Session
) -> int:
    """把 dws_contact_360 中指向从公司(secondary_id)的联系人改挂到主公司(primary_id)。

    dws_contact_360 仅含 customer_id（无公司名列），合并靠重新指向主公司 id 实现。
    若主公司已存在相同 (customer_id, mobile) 行则删除从公司行，避免唯一键冲突。
    """
    if not secondary_id or not primary_id or secondary_id == primary_id:
        return 0
    try:
        # 删除会从公司产生冲突（与主公司已存在 customer_id+mobile 重复）的行
        db.execute(
            text("""
                DELETE c
                FROM dws_contact_360 c
                JOIN dws_contact_360 p
                  ON p.customer_id = :primary_id AND p.mobile = c.mobile
                WHERE c.customer_id = :secondary_id
            """),
            {"primary_id": primary_id, "secondary_id": secondary_id},
        )
        # 其余从公司行改挂主公司
        res = db.execute(
            text("""
                UPDATE dws_contact_360
                SET customer_id = :primary_id
                WHERE customer_id = :secondary_id
            """),
            {"primary_id": primary_id, "secondary_id": secondary_id},
        )
        return res.rowcount or 0
    except Exception as e:
        logger.warning(f"重新挂接 dws_contact_360 失败: {e}")
        return 0


def _merge_one_source(
    src_name: str,
    src_id: Any,
    target_name: str,
    target_id: Any,
    db: Session,
    merge_stats: Dict[str, Any],
) -> None:
    """把单个源公司合并到目标公司（基于 dws 四张表）。"""
    # dws_contact_360 仅含 customer_id 无公司名：先从公司联系人改挂到主公司 id（避免孤儿）
    relink = _relink_contact_360(src_id, target_id, db)
    merge_stats["contact_360_relink"] = merge_stats.get("contact_360_relink", 0) + relink

    for updater, label in [
        (_update_c360_company_name, "customer_360"),
        (_update_contact_mapping_company_name, "contact_mapping"),
        (_update_interaction_company_name, "interaction_detail"),
    ]:
        try:
            count = updater(src_name, target_name, db)
            merge_stats[label] = merge_stats.get(label, 0) + count
        except Exception as e:
            logger.warning(f"  更新 {label} 表失败: {e}")
            merge_stats[label] = f"error: {e}"


def _update_c360_company_name(old_name: str, new_name: str, db: Session) -> int:
    """合并 dws_customer_360：把从公司行名改为总（主）公司名。

    customer_name 有唯一键 uk_customer_name：若总（主）公司名已存在则删除从公司行
    （其聚合指标由后续 ETL 全量重建从已改名的 contact_mapping/interaction_detail 重新汇总），
    否则直接改名，避免唯一键冲突。
    """
    if not old_name or not new_name or old_name == new_name:
        return 0
    try:
        exists = db.execute(
            text("SELECT 1 FROM dws_customer_360 WHERE customer_name = :new LIMIT 1"),
            {"new": new_name},
        ).scalar()
        if exists:
            res = db.execute(
                text(
                    "DELETE FROM dws_customer_360 "
                    "WHERE customer_name = :old AND customer_name != :new"
                ),
                {"old": old_name, "new": new_name},
            )
        else:
            res = db.execute(
                text(
                    "UPDATE dws_customer_360 SET customer_name = :new "
                    "WHERE customer_name = :old AND customer_name != :new"
                ),
                {"old": old_name, "new": new_name},
            )
        count = res.rowcount or 0
        if count > 0:
            logger.info(f"  更新 dws_customer_360: {count} 条 '{old_name}' -> '{new_name}'")
        return count
    except Exception as e:
        logger.warning(f"更新 dws_customer_360 失败: {e}")
        return 0


def _update_contact_mapping_company_name(old_name: str, new_name: str, db: Session) -> int:
    """合并 dws_contact_mapping：把从公司联系人改挂到总（主）公司名。

    (customer_name, mobile) 有唯一键 uk_customer_mobile：先删除与主公司已存在相同手机号的
    从公司冲突行，再改剩余行，避免唯一键冲突。
    """
    if not old_name or not new_name or old_name == new_name:
        return 0
    try:
        # 删除从公司与主公司已存在 (customer_name, mobile) 重复的冲突行
        db.execute(
            text("""
                DELETE cm
                FROM dws_contact_mapping cm
                JOIN dws_contact_mapping p
                  ON p.customer_name = :new AND p.mobile = cm.mobile
                WHERE cm.customer_name = :old
            """),
            {"old": old_name, "new": new_name},
        )
        res = db.execute(
            text("""
                UPDATE dws_contact_mapping
                SET customer_name = :new
                WHERE customer_name = :old AND customer_name != :new
            """),
            {"old": old_name, "new": new_name},
        )
        count = res.rowcount or 0
        if count > 0:
            logger.info(f"  更新 dws_contact_mapping: {count} 条 '{old_name}' -> '{new_name}'")
        return count
    except Exception as e:
        logger.warning(f"更新 dws_contact_mapping 失败: {e}")
        return 0


def _update_interaction_company_name(old_name: str, new_name: str, db: Session) -> int:
    """合并 dws_interaction_detail：把从公司互动改名到总（主）公司名。

    该表唯一键为 (source_table, source_id)，无公司名唯一约束，可直接改名。
    """
    if not old_name or not new_name or old_name == new_name:
        return 0
    try:
        res = db.execute(
            text("""
                UPDATE dws_interaction_detail
                SET customer_name = :new
                WHERE customer_name = :old AND customer_name != :new
            """),
            {"old": old_name, "new": new_name},
        )
        count = res.rowcount or 0
        if count > 0:
            logger.info(f"  更新 dws_interaction_detail: {count} 条 '{old_name}' -> '{new_name}'")
        return count
    except Exception as e:
        logger.warning(f"更新 dws_interaction_detail 失败: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# 增量去重支持
# ─────────────────────────────────────────────────────────────────────────────

# 上一次去重运行时间记录（文件存储，简单可靠）
_dedup_last_run_file = Path(__file__).parent.parent.parent.parent / "data" / "dedup_last_run.txt"


def get_last_dedup_time() -> Optional[str]:
    """获取上次去重运行时间。"""
    try:
        if _dedup_last_run_file.exists():
            return _dedup_last_run_file.read_text().strip()
    except Exception:
        pass
    return None


def save_last_dedup_time(time_str: str) -> None:
    """保存最后一次去重运行时间。"""
    try:
        _dedup_last_run_file.parent.mkdir(exist_ok=True)
        _dedup_last_run_file.write_text(time_str)
    except Exception as e:
        logger.warning(f"保存去重运行时间失败: {e}")


def fetch_new_or_updated_companies(
    db: Session, since: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    增量获取新增或更新的公司名称。

    如果 since 为 None，则回退到全量获取。

    Args:
        db: 数据库会话
        since: 起始时间（ISO 格式）

    Returns:
        公司列表
    """
    if not since:
        return fetch_all_company_names(db)

    companies: Dict[str, Dict[str, Any]] = {}

    try:
        sql = text("""
            SELECT DISTINCT customer_name, id
            FROM dws_customer_360
            WHERE customer_name IS NOT NULL AND customer_name != ''
              AND updated_at >= :since
        """)
        rows = db.execute(sql, {"since": since}).fetchall()
        for row_name, row_id in rows:
            src_entry = {"table": "dws_customer_360", "record_id": row_id}
            if row_name not in companies:
                companies[row_name] = {
                    "name": row_name,
                    "customer_id": row_id,
                    "sources": [src_entry],
                }

        if rows:
            logger.info(f"增量模式: 发现 {len(rows)} 个新增/更新的公司（since {since}）")
    except Exception as e:
        logger.warning(f"增量查询 dws_customer_360 失败: {e}，回退到全量模式")
        return fetch_all_company_names(db)

    # 如果增量结果太少，回退到全量模式
    if len(companies) < 2:
        logger.info("增量结果不足，回退到全量模式")
        return fetch_all_company_names(db)

    return list(companies.values())


# ─────────────────────────────────────────────────────────────────────────────
# Run Full Deduplication (Background)
# ─────────────────────────────────────────────────────────────────────────────

def run_deduplication_background() -> None:
    """Run the full deduplication process in background thread."""
    global _dedup_progress

    with _dedup_lock:
        if _dedup_progress["status"] == "running":
            return

        _dedup_progress["status"] = "running"
        _dedup_progress["progress"] = 0
        _dedup_progress["overall_progress"] = 0.0
        _dedup_progress["phase_index"] = 0
        _dedup_progress["phase_progress"] = 0.0
        _dedup_progress["results"] = None
        _dedup_progress["details"] = None
        _dedup_progress["eta_seconds"] = None
        _dedup_progress["elapsed_seconds"] = None
        _dedup_progress["throughput"] = None
        _dedup_progress["started_at"] = datetime.now().isoformat()

    try:
        # 生成候选对（内部自行管理会话：读取/写入各用独立短生命周期连接，
        # 中间的嵌入计算 / FAISS 等长耗时处理不持有任何连接，避免被服务端回收）。
        results = generate_review_pairs(incremental=False)

        # 进入阶段 4（完成）的前半段：自动合并尚未落地，进度仅推进到 99.3%，
        # 让前端明确「任务仍在运行、尚未完成」，避免提前停止轮询 / 误判完成。
        _set_phase_progress(4, 0.3, extra={
            "message": "评分与写入队列完成，正在自动合并高置信度候选对...",
        })

        # 自动合并高置信度对：独立短生命周期会话，避免复用被长耗时处理拖垮的连接。
        auto_merged = 0
        try:
            from app.database import SessionLocal
            with SessionLocal() as db:
                auto_merged = auto_merge_high_confidence(db)
        except Exception as _e:
            logger.error("自动升级候选对失败（不影响后续落库）: %s", _e, exc_info=True)

        # 阶段 4 推进到 0.6（整体 99.6%）：自动升级完成，开始落库到 company_merge_map。
        _set_phase_progress(4, 0.6, extra={
            "message": f"已升级 {auto_merged} 对自动合并，正在落库合并关系到 company_merge_map...",
        })

        # 关键修复：无论自动升级是否成功，都必须把 generate 直接写入的
        # status='auto_merged' 候选对持久化进 company_merge_map。否则会出现
        # 「标记了自动合并、却没真正合并」的缺口。sync_auto_merged_to_map 内部
        # 自开会话、逐行容错，单条脏数据不会拖垮整批落库。
        persisted = 0
        try:
            from app.services.company_dedup.company_merge import sync_auto_merged_to_map
            persisted = sync_auto_merged_to_map()
            logger.info(f"Persisted {persisted} auto-merges to company_merge_map")
        except Exception as _e:
            logger.error("自动合并落库失败: %s", _e, exc_info=True)
        results["auto_merged_final"] = auto_merged
        results["auto_merged_persisted"] = persisted

        # 记录本次运行时间，供下次增量去重使用
        run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_last_dedup_time(run_time)
        results["run_time"] = run_time

        with _dedup_lock:
            _dedup_progress["status"] = "completed"
            _dedup_progress["results"] = results
            _set_phase_progress(4, 1.0, extra={
                "completed": results.get("new_pairs_found", 0),
                "total": results.get("total_companies", 0),
                "message": f"去重完成：新增 {results.get('new_pairs_found', 0)} 个待审核对",
            })

        logger.info(f"Deduplication completed: {results}")

    except Exception as e:
        logger.error(f"Deduplication failed: {e}", exc_info=True)
        with _dedup_lock:
            _dedup_progress["status"] = "failed"
            _dedup_progress["step"] = f"Error: {str(e)}"
            _dedup_progress["results"] = {"error": str(e)}


def get_dedup_progress() -> Dict[str, Any]:
    """Get the current deduplication progress."""
    with _dedup_lock:
        return dict(_dedup_progress)


def start_deduplication() -> Dict[str, Any]:
    """Start the deduplication process in background."""
    with _dedup_lock:
        if _dedup_progress["status"] == "running":
            return {
                "success": False,
                "message": "Deduplication already running",
                "progress": dict(_dedup_progress),
            }

    # Start in background thread
    thread = threading.Thread(target=run_deduplication_background, daemon=True)
    thread.start()

    return {
        "success": True,
        "message": "Deduplication started",
        "progress": get_dedup_progress(),
    }
