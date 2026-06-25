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

import hashlib
import json
import logging
import httpx
import re
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

# Data source priority (higher = more trusted)
SOURCE_PRIORITY = {
    'crm': 6, 'lead': 5, 'tianrun_session': 4,
    'zhique_behavior': 3, 'linkflow': 2, 'email_click': 1,
}

# Global dedup progress tracking
_dedup_progress = {
    "status": "idle",
    "step": "",
    "progress": 0,
    "total": 0,
    "results": None,
    "details": None,  # 详细进度信息: {"step_name": "", "completed": 0, "total": 0, "message": ""}
}
_dedup_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# SQLite Embeddings Cache
# ─────────────────────────────────────────────────────────────────────────────

def get_cache_path() -> Path:
    """Get the path to the embeddings cache database."""
    project_root = Path(__file__).parent.parent.parent.parent
    cache_dir = project_root / "data"
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


def get_cached_embedding(name: str) -> Optional[np.ndarray]:
    """Get cached embedding for a company name."""
    cache_path = get_cache_path()
    conn = sqlite3.connect(str(cache_path))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT embedding FROM embeddings
        WHERE company_name = ? OR normalized_name = ?
    """, (name, name))

    result = cursor.fetchone()
    conn.close()

    if result:
        return np.frombuffer(result[0], dtype=np.float32)
    return None


def cache_embedding(name: str, normalized_name: str, embedding: np.ndarray) -> None:
    """Cache embedding for a company name."""
    cache_path = get_cache_path()
    conn = sqlite3.connect(str(cache_path))
    cursor = conn.cursor()

    cursor.execute("""
        REPLACE INTO embeddings (company_name, normalized_name, embedding, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (name, normalized_name, embedding.tobytes()))

    conn.commit()
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


def compute_embeddings_batch(names: List[str], progress_callback: Optional[Callable[[int, int], None]] = None) -> List[np.ndarray]:
    """
    Compute embeddings for a batch of company names using real API.
    Results cached in SQLite to avoid recomputation.

    Args:
        names: List of company names
        progress_callback: Optional callback function to report progress (completed, total)

    Returns:
        List of embedding vectors (1536-dim for text-embedding-3-small)
    """
    from app.config import settings

    init_embeddings_cache()

    embeddings: List[np.ndarray] = []
    uncached_indices: List[int] = []  # indices with no cache hit
    uncached_names: List[str] = []    # names needing real embedding

    for i, name in enumerate(names):
        cached = get_cached_embedding(name)
        if cached is not None:
            embeddings.append(cached)
        else:
            embeddings.append(None)  # placeholder, will fill below
            uncached_indices.append(i)
            uncached_names.append(name)

    # If all cached, return immediately
    if not uncached_names:
        if progress_callback:
            progress_callback(len(names), len(names))
        return embeddings

    # Compute real embeddings for uncached names via API
    # 优先使用独立的 Embedding API 配置，否则回退到 LLM 配置，最后用 hash 兜底
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL

    if not api_key or not base_url:
        logger.warning("Embedding API not configured, falling back to hash embedding")
        # Fallback: use normalized name hash (deterministic but meaningful)
        # hash 计算很快，每次都更新进度以确保前端能看到连续变化
        for i, idx in enumerate(uncached_indices):
            name = names[idx]
            normalized = normalize_company_name(name)
            # Simple char-frequency vector (128-dim)
            vec = np.zeros(128, dtype=np.float32)
            for ch in normalized[:200]:
                vec[hash(ch) % 128] += 0.1
            # L2 normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            cache_embedding(name, normalized, vec)
            embeddings[idx] = vec
            # 每条都更新进度（hash 计算很快，不用担心性能）
            if progress_callback:
                progress_callback(i + 1, len(uncached_indices))
        return embeddings

    # Call real embedding API in batches
    batch_size = 100
    resolved_url = f"{base_url.rstrip('/')}/embeddings"
    completed_count = len(names) - len(uncached_names)  # 已缓存的数量

    for batch_start in range(0, len(uncached_names), batch_size):
        batch_names = uncached_names[batch_start:batch_start + batch_size]
        batch_indices = uncached_indices[batch_start:batch_start + batch_size]

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    resolved_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "text-embedding-3-small",
                        "input": batch_names,
                        "encoding_format": "float",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("data", []):
                    pos = item.get("index", 0)
                    global_idx = batch_indices[pos]
                    emb = np.array(item["embedding"], dtype=np.float32)
                    # L2 normalize
                    norm = np.linalg.norm(emb)
                    if norm > 0:
                        emb = emb / norm
                    name = names[global_idx]
                    normalized = normalize_company_name(name)
                    cache_embedding(name, normalized, emb)
                    embeddings[global_idx] = emb

                completed_count += len(batch_names)
                if progress_callback:
                    progress_callback(completed_count, len(names))
                logger.info(f"  Embedded batch {batch_start // batch_size + 1}: "
                          f"{len(batch_names)} names ({completed_count}/{len(names)})")

        except Exception as e:
            logger.warning(f"Embedding API call failed for batch {e}, "
                          f"falling back to hash embedding")
            for i, idx in enumerate(batch_indices):
                name = names[idx]
                normalized = normalize_company_name(name)
                vec = np.zeros(128, dtype=np.float32)
                for ch in normalized[:200]:
                    vec[hash(ch) % 128] += 0.1
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                cache_embedding(name, normalized, vec)
                embeddings[idx] = vec
                completed_count += 1
                # 每处理10个才更新一次进度（减少频率）
                if progress_callback and i % 10 == 0:
                    progress_callback(completed_count, len(names))
            # 最后再更新一次，确保进度完整
            if progress_callback:
                progress_callback(completed_count, len(names))

    return embeddings


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
    # 优化：降低 k 值从 100 到 50，减少返回的候选对数量
    k = min(n, 50)  # 最多返回 50 个最相似邻居
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
    
    # 1. Levenshtein distance based similarity (权重 0.30)
    max_len = max(len(norm_a), len(norm_b))
    if max_len > 0:
        lev_dist = _levenshtein(norm_a, norm_b)
        lev_score = (1 - lev_dist / max_len) * 100
        scores.append(lev_score * 0.30)

    # 2. Substring containment (权重 0.25) - 允许与其他特征叠加
    if norm_a in norm_b:
        containment = len(norm_a) / len(norm_b) * 100
        scores.append(containment * 0.25)
    if norm_b in norm_a:
        containment = len(norm_b) / len(norm_a) * 100
        scores.append(containment * 0.25)

    # 3. Common prefix/suffix (权重 0.20)
    # 公共前缀
    prefix_len = 0
    for i in range(min(len(norm_a), len(norm_b))):
        if norm_a[i] == norm_b[i]:
            prefix_len += 1
        else:
            break
    if prefix_len > 0:
        prefix_score = (prefix_len / max(len(norm_a), len(norm_b))) * 100
        scores.append(prefix_score * 0.10)
    
    # 公共后缀
    suffix_len = 0
    for i in range(1, min(len(norm_a), len(norm_b)) + 1):
        if norm_a[-i] == norm_b[-i]:
            suffix_len += 1
        else:
            break
    if suffix_len > 0:
        suffix_score = (suffix_len / max(len(norm_a), len(norm_b))) * 100
        scores.append(suffix_score * 0.10)

    # 4. Token-based similarity (权重 0.25)
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    if tokens_a and tokens_b:
        common_tokens = len(tokens_a & tokens_b)
        total_tokens = len(tokens_a | tokens_b)
        if total_tokens > 0:
            token_score = (common_tokens / total_tokens) * 100
            scores.append(token_score * 0.25)

    # 5. Character-level Jaccard similarity (权重 0.20)
    set_a = set(norm_a)
    set_b = set(norm_b)
    if set_a or set_b:
        common_chars = len(set_a & set_b)
        total_chars = len(set_a | set_b)
        if total_chars > 0:
            jaccard = (common_chars / total_chars) * 100
            scores.append(jaccard * 0.20)

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

    # 定义要检查的表和字段（字段名与实际表结构一致）
    tables_to_check = [
        {
            "table": "ods_zhique_contact_day",
            "company_field": "related_company",   # 实际列名
            "phone_field": "phone",
            "email_field": "email",
        },
        {
            "table": "ods_crm_contact_day",
            "company_field": "customer_name",     # 实际列名
            "phone_field": "mobile",
            "email_field": "email",
        },
        {
            "table": "ods_marketing_lead_day",
            "company_field": "customer_company",  # 主公司名列
            "phone_field": "contact_phone",
            "email_field": "email",
        },
    ]

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

            # 检查共享邮箱
            email_sql = text(f"""
                SELECT COUNT(DISTINCT c1.{email_field}) as shared_emails
                FROM {table_name} c1
                JOIN {table_name} c2 ON c1.{email_field} = c2.{email_field}
                WHERE c1.{company_field} LIKE :name_a
                  AND c2.{company_field} LIKE :name_b
                  AND c1.{email_field} IS NOT NULL AND c1.{email_field} != ''
            """)

            phone_result = db.execute(
                phone_sql, {"name_a": f"%{name_a}%", "name_b": f"%{name_b}%"}
            ).scalar() or 0

            email_result = db.execute(
                email_sql, {"name_a": f"%{name_a}%", "name_b": f"%{name_b}%"}
            ).scalar() or 0

            total_shared += phone_result + email_result
        
        if total_shared > 0:
            evidence_score = min(100.0, total_shared * 20.0)  # 调整乘数从25到20
            evidence_count = total_shared

    except Exception as e:
        logger.warning(f"Error calculating evidence score: {e}")
        evidence_score = 0.0

    return round(evidence_score, 2), evidence_count


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

    # 定义要检查的表（字段名与实际表结构一致）
    tables_to_check = [
        {"table": "ods_zhique_contact_day", "company_field": "related_company", "phone_field": "phone", "email_field": "email"},
        {"table": "ods_crm_contact_day", "company_field": "customer_name", "phone_field": "mobile", "email_field": "email"},
        {"table": "ods_marketing_lead_day", "company_field": "customer_company", "phone_field": "contact_phone", "email_field": "email"},
    ]

    # 聚合所有公司的联系信息
    company_phones: Dict[str, set] = defaultdict(set)
    company_emails: Dict[str, set] = defaultdict(set)

    num_tables = len(tables_to_check)
    for table_idx, table_config in enumerate(tables_to_check):
        table_name = table_config["table"]
        company_field = table_config["company_field"]
        phone_field = table_config["phone_field"]
        email_field = table_config["email_field"]

        # 进度：告知前端正在查询哪个表
        if progress_callback:
            progress_callback(0, total_pairs,
                             f"正在查询 {table_name} 的联系数据 ({table_idx + 1}/{num_tables})...")

        # 为每个表单独构建 LIKE 查询条件，使用该表实际的列名
        like_parts = []
        params: Dict[str, str] = {}
        for idx, name in enumerate(all_companies):
            like_parts.append(f"{company_field} LIKE :name_{idx}")
            params[f"name_{idx}"] = f"%{name}%"
        like_clause = " OR ".join(like_parts) if like_parts else "1=0"

        # 批量查询：公司 → 电话集合
        try:
            phone_sql = text(f"""
                SELECT {company_field}, {phone_field}
                FROM {table_name}
                WHERE ({like_clause})
                  AND {phone_field} IS NOT NULL AND {phone_field} != ''
            """)
            phone_rows = db.execute(phone_sql, params).fetchall()
            for company_name, phone in phone_rows:
                # 匹配回原始公司名
                matched = False
                for orig_name in all_companies:
                    if company_name and orig_name in company_name:
                        company_phones[orig_name].add(phone)
                        matched = True
                        break
                if not matched:
                    # 模糊匹配
                    for orig_name in all_companies:
                        if company_name and orig_name and (
                            company_name in orig_name or
                            normalize_company_name(company_name) == normalize_company_name(orig_name)
                        ):
                            company_phones[orig_name].add(phone)
                            break
        except Exception as e:
            logger.warning(f"Batch phone query failed for {table_name}: {e}")

        if progress_callback:
            progress_callback(0, total_pairs,
                             f"已完成 {table_name} 电话查询 ({table_idx + 1}/{num_tables})，正在查邮箱...")

        # 批量查询：公司 → 邮箱集合
        try:
            email_sql = text(f"""
                SELECT {company_field}, {email_field}
                FROM {table_name}
                WHERE ({like_clause})
                  AND {email_field} IS NOT NULL AND {email_field} != ''
            """)
            email_rows = db.execute(email_sql, params).fetchall()
            for company_name, email in email_rows:
                matched = False
                for orig_name in all_companies:
                    if company_name and orig_name in company_name:
                        company_emails[orig_name].add(email)
                        matched = True
                        break
                if not matched:
                    for orig_name in all_companies:
                        if company_name and orig_name and (
                            company_name in orig_name or
                            normalize_company_name(company_name) == normalize_company_name(orig_name)
                        ):
                            company_emails[orig_name].add(email)
                            break
        except Exception as e:
            logger.warning(f"Batch email query failed for {table_name}: {e}")

        if progress_callback:
            progress_callback(0, total_pairs,
                             f"已完成 {table_name} 查询 ({table_idx + 1}/{num_tables})")

    # 所有表查询完成，开始计算共享联系人
    if progress_callback:
        progress_callback(0, total_pairs, "数据收集完成，正在计算共享联系人...")

    # 在内存中计算每对的共享联系人
    scores: Dict[Tuple[str, str], Tuple[float, int]] = {}
    if progress_callback:
        progress_callback(0, total_pairs, "正在从数据库收集证据...")
    # 每 100 对更新一次进度，并添加微小延迟让前端轮询能捕获到中间状态
    for pair_idx, (name_a, name_b) in enumerate(company_pairs):
        phones_a = company_phones.get(name_a, set())
        phones_b = company_phones.get(name_b, set())
        emails_a = company_emails.get(name_a, set())
        emails_b = company_emails.get(name_b, set())

        shared_phones = len(phones_a & phones_b)
        shared_emails = len(emails_a & emails_b)
        shared_contacts = shared_phones + shared_emails

        if shared_contacts > 0:
            evidence_score = min(100.0, shared_contacts * 20.0)
        else:
            evidence_score = 0.0

        scores[(name_a, name_b)] = (round(evidence_score, 2), shared_contacts)

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

DEFAULT_LLM_MODEL = "qwen3.6-plus"

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
        proxy = (rule_score * 0.5 + evidence_score * 0.5) / 100.0
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
        resolved_base_url = base_url or "https://api.openai.com/v1"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{resolved_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEFAULT_LLM_MODEL,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 100,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"LLM judge call failed: {e}")
        # Fallback on error
        proxy = (rule_score * 0.5 + evidence_score * 0.5) / 100.0
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
        llm_score = (rule_score * 0.5 + evidence_score * 0.5) / 100.0
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
        rule_score * 0.35 +
        evidence_score * 0.40 +
        llm_score * 0.25
    )

    return round(min(100.0, final_score), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Fetch Company Names
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_company_names(db: Session) -> List[Dict[str, Any]]:
    """
    Fetch all unique company names from all sources.
    照搬旧版 company_dedup_wasted.py 的数据读取逻辑（表字段名与旧版保持一致）。

    Sources:
    - dws_customer_360 (Customer 360 view)
    - ods_zhique_behavior_list_day (Behavior data)
    - ods_marketing_lead_day (Marketing leads)
    - ods_zhique_contact_day (Contacts)
    - ods_crm_contact_day (CRM contacts)

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

    # Source 1: dws_customer_360
    try:
        t0 = time.time()
        logger.info("[1/5] 查询 dws_customer_360...")
        sql1 = text("""
            SELECT DISTINCT customer_name, id
            FROM dws_customer_360
            WHERE customer_name IS NOT NULL AND customer_name != ''
        """)
        result1 = db.execute(sql1).fetchall()
        for row_name, row_id in result1:
            if row_name not in companies:
                companies[row_name] = {
                    "name": row_name,
                    "customer_id": row_id,
                    "sources": ["dws_customer_360"]
                }
            else:
                if "dws_customer_360" not in companies[row_name]["sources"]:
                    companies[row_name]["sources"].append("dws_customer_360")
        logger.info(f"[1/5] dws_customer_360: {len(result1)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[1/5] dws_customer_360 查询失败: {e}")

    # Source 2: ods_zhique_behavior_list_day
    try:
        t0 = time.time()
        logger.info("[2/5] 查询 ods_zhique_behavior_list_day...")
        sql2 = text("""
            SELECT DISTINCT company_name
            FROM ods_zhique_behavior_list_day
            WHERE company_name IS NOT NULL AND company_name != ''
        """)
        result2 = db.execute(sql2).fetchall()
        for (company_name,) in result2:
            if company_name not in companies:
                companies[company_name] = {
                    "name": company_name,
                    "customer_id": None,
                    "sources": ["ods_zhique_behavior_list_day"]
                }
            else:
                if "ods_zhique_behavior_list_day" not in companies[company_name]["sources"]:
                    companies[company_name]["sources"].append("ods_zhique_behavior_list_day")
        logger.info(f"[2/5] ods_zhique_behavior_list_day: {len(result2)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[2/5] ods_zhique_behavior_list_day 查询失败: {e}")

    # Source 3: ods_marketing_lead_day
    try:
        t0 = time.time()
        logger.info("[3/5] 查询 ods_marketing_lead_day...")
        sql3 = text("""
            SELECT DISTINCT COALESCE(final_company_name, customer_company, opp_customer_name) AS company_name
            FROM ods_marketing_lead_day
            WHERE COALESCE(final_company_name, customer_company, opp_customer_name) IS NOT NULL
              AND COALESCE(final_company_name, customer_company, opp_customer_name) != ''
        """)
        result3 = db.execute(sql3).fetchall()
        for (company_name,) in result3:
            if company_name not in companies:
                companies[company_name] = {
                    "name": company_name,
                    "customer_id": None,
                    "sources": ["ods_marketing_lead_day"]
                }
            else:
                if "ods_marketing_lead_day" not in companies[company_name]["sources"]:
                    companies[company_name]["sources"].append("ods_marketing_lead_day")
        logger.info(f"[3/5] ods_marketing_lead_day: {len(result3)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[3/5] ods_marketing_lead_day 查询失败: {e}")

    # Source 4: ods_zhique_contact_day
    try:
        t0 = time.time()
        logger.info("[4/5] 查询 ods_zhique_contact_day...")
        sql4 = text("""
            SELECT DISTINCT related_company
            FROM ods_zhique_contact_day
            WHERE related_company IS NOT NULL AND related_company != ''
        """)
        result4 = db.execute(sql4).fetchall()
        for (company_name,) in result4:
            if company_name not in companies:
                companies[company_name] = {
                    "name": company_name,
                    "customer_id": None,
                    "sources": ["ods_zhique_contact_day"]
                }
            else:
                if "ods_zhique_contact_day" not in companies[company_name]["sources"]:
                    companies[company_name]["sources"].append("ods_zhique_contact_day")
        logger.info(f"[4/5] ods_zhique_contact_day: {len(result4)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[4/5] ods_zhique_contact_day 查询失败: {e}")

    # Source 5: ods_crm_contact_day
    try:
        t0 = time.time()
        logger.info("[5/5] 查询 ods_crm_contact_day...")
        sql5 = text("""
            SELECT DISTINCT customer_name
            FROM ods_crm_contact_day
            WHERE customer_name IS NOT NULL AND customer_name != ''
        """)
        result5 = db.execute(sql5).fetchall()
        for (company_name,) in result5:
            if company_name not in companies:
                companies[company_name] = {
                    "name": company_name,
                    "customer_id": None,
                    "sources": ["ods_crm_contact_day"]
                }
            else:
                if "ods_crm_contact_day" not in companies[company_name]["sources"]:
                    companies[company_name]["sources"].append("ods_crm_contact_day")
        logger.info(f"[5/5] ods_crm_contact_day: {len(result5)} 条, 耗时 {time.time()-t0:.1f}s")
    except Exception as e:
        logger.warning(f"[5/5] ods_crm_contact_day 查询失败: {e}")

    result = list(companies.values())
    logger.info(f"数据读取完成: 共 {len(result)} 个唯一公司名, 总耗时 {time.time()-total_start:.1f}s")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Generate Review Pairs
# ─────────────────────────────────────────────────────────────────────────────

def generate_review_pairs(
    db: Session,
    incremental: bool = True
) -> Dict[str, Any]:
    """
    生成所有潜在重复对并插入 review_candidate。

    Args:
        db: 数据库会话
        incremental: 是否使用增量模式（仅处理新增/更新的公司）

    Returns:
        去重运行统计信息
    """
    global _dedup_progress

    # Step 1: 获取公司名称（增量或全量）
    _dedup_progress["step"] = "获取公司名称"
    _dedup_progress["progress"] = 10
    _dedup_progress["details"] = {"step_name": "获取公司名称", "completed": 0, "total": 0, "message": "正在从数据库读取公司名称..."}

    if incremental:
        last_time = get_last_dedup_time()
        if last_time:
            companies = fetch_new_or_updated_companies(db, since=last_time)
            logger.info(f"增量去重: since={last_time}, 获取 {len(companies)} 家公司")
        else:
            companies = fetch_all_company_names(db)
            logger.info(f"首次运行全量去重: {len(companies)} 家公司")
    else:
        companies = fetch_all_company_names(db)

    # 过滤 & 标准化：
    # (1) 公司名称不能为空，空名称直接过滤掉
    # (2) customer_id 为空的公司，将其 id 设为 "default_id"（允许无真实ID的公司参与去重）
    total_before_filter = len(companies)
    companies_filtered = []
    filtered_empty_name = 0
    set_default_id_count = 0
    for c in companies:
        name = (c.get("name") or "").strip()
        if not name:
            filtered_empty_name += 1
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
    if set_default_id_count > 0:
        logger.info(f"{set_default_id_count} 个公司缺少 customer_id，已设为 default_id")
    _dedup_progress["details"] = {
        "step_name": "获取公司名称",
        "completed": len(companies),
        "total": total_before_filter,
        "message": f"已获取 {total_before_filter} 家公司（过滤空名称 {filtered_empty_name}，default_id {set_default_id_count}）"
    }
    
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
    _dedup_progress["step"] = "Computing embeddings"
    _dedup_progress["progress"] = 30
    _dedup_progress["details"] = {"step_name": "Computing embeddings", "completed": 0, "total": len(names), "message": f"正在计算嵌入向量... (0/{len(names)})"}
    
    def _embedding_progress_callback(completed: int, total: int):
        """Embedding 计算进度回调"""
        global _dedup_progress
        _dedup_progress["details"] = {
            "step_name": "Computing embeddings",
            "completed": completed,
            "total": total,
            "message": f"正在计算嵌入向量... ({completed}/{total})"
        }
        # 更新总体进度 (30-50 范围)，保留 2 位小数
        _dedup_progress["progress"] = round(30 + 20 * completed / total, 2)
    
    embeddings = compute_embeddings_batch(names, progress_callback=_embedding_progress_callback)

    # Step 3: Find similar pairs
    _dedup_progress["step"] = "Finding similar pairs"
    _dedup_progress["progress"] = 50
    _dedup_progress["details"] = {"step_name": "Finding similar pairs", "completed": 0, "total": len(names), "message": f"正在查找相似公司对... (输入: {len(names)} 个公司)"}
    
    def _similar_pairs_progress_callback(completed: int, total: int, message: str):
        """相似对查找进度回调"""
        global _dedup_progress
        _dedup_progress["details"] = {
            "step_name": "Finding similar pairs",
            "completed": completed,
            "total": total,
            "message": message
        }
        # 更新总体进度 (50-60 范围)，保留 2 位小数
        if total > 0:
            _dedup_progress["progress"] = round(50 + 10 * completed / total, 2)
    
    # 使用阈值0.70（参考代码）
    similar_pairs = find_similar_pairs(embeddings, names, threshold=0.70, 
                                        progress_callback=_similar_pairs_progress_callback)
    
    _dedup_progress["details"] = {"step_name": "Finding similar pairs", "completed": len(similar_pairs), "total": len(names), "message": f"找到 {len(similar_pairs)} 个相似对 (输入: {len(names)} 个公司)"}
    
    # 仅记录关键诊断日志
    logger.info(f"获取到 {len(names)} 个公司名，找到 {len(similar_pairs)} 个相似对（阈值=0.70）")

    # Step 4: Score and insert into review queue
    _dedup_progress["step"] = "计算证据评分（批量）"
    _dedup_progress["progress"] = 60
    _dedup_progress["details"] = {"step_name": "计算证据评分（批量）", "completed": 0, "total": len(similar_pairs), "message": f"正在计算证据评分... (0/{len(similar_pairs)})"}

    def _evidence_progress_callback(completed: int, total: int, message: str):
        """证据评分进度回调"""
        global _dedup_progress
        _dedup_progress["details"] = {
            "step_name": "计算证据评分（批量）",
            "completed": completed,
            "total": total,
            "message": message
        }
        # 更新总体进度 (60-65 范围)，保留 2 位小数
        if total > 0:
            _dedup_progress["progress"] = round(60 + 5 * completed / total, 2)

    # 批量计算证据评分（减少 N+1 查询）
    pair_names = [(companies[idx_a]["name"], companies[idx_b]["name"])
                  for idx_a, idx_b, _sim in similar_pairs]
    batch_evidence = batch_calculate_evidence_scores(pair_names, db,
                                                      progress_callback=_evidence_progress_callback)
    
    _dedup_progress["details"] = {"step_name": "计算证据评分（批量）", "completed": len(similar_pairs), "total": len(similar_pairs), "message": f"已完成证据评分 ({len(similar_pairs)}/{len(similar_pairs)})"}

    _dedup_progress["step"] = "检查已存在的pair"
    _dedup_progress["progress"] = 65
    _dedup_progress["details"] = {"step_name": "检查已存在的pair", "completed": 0, "total": 0, "message": "正在检查已存在的pair..."}

    # 批量查询已存在的pair，避免循环中逐条查询
    existing_pairs: set = set()
    try:
        # 获取 review_candidate 表中所有已存在的pair
        existing_sql = text("""
            SELECT candidate_a_name, candidate_b_name
            FROM review_candidate
        """)
        existing_rows = db.execute(existing_sql).fetchall()
        
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

    _dedup_progress["step"] = "计算综合评分并写入队列"
    _dedup_progress["progress"] = 70
    _dedup_progress["details"] = {"step_name": "计算综合评分并写入队列", "completed": 0, "total": len(similar_pairs), "message": f"正在计算综合评分并写入队列... (0/{len(similar_pairs)})"}

    new_pairs_count = 0
    auto_merged_count = 0
    need_review_count = 0
    
    # 诊断：收集评分数据用于统计分析
    all_rule_scores = []
    all_evidence_scores = []
    all_llm_scores = []
    all_final_scores = []

    for pair_idx, (idx_a, idx_b, similarity) in enumerate(similar_pairs):
        company_a = companies[idx_a]
        company_b = companies[idx_b]

        # 每处理 100 个 pair 更新一次进度（减少频率，提高性能）
        if pair_idx % 100 == 0:
            _dedup_progress["details"] = {
                "step_name": "计算综合评分并写入队列",
                "completed": pair_idx,
                "total": len(similar_pairs),
                "message": f"正在计算综合评分并写入队列... ({pair_idx}/{len(similar_pairs)})"
            }
            # 更新总体进度 (70-99 范围)，保留 2 位小数
            _dedup_progress["progress"] = round(70 + 29 * pair_idx / len(similar_pairs), 2)

        # 计算规则评分
        rule_score = calculate_rule_score(company_a["name"], company_b["name"])

        # 从批量结果获取证据评分
        key = (company_a["name"], company_b["name"])
        rev_key = (company_b["name"], company_a["name"])
        if key in batch_evidence:
            evidence_score, shared_count = batch_evidence[key]
        elif rev_key in batch_evidence:
            evidence_score, shared_count = batch_evidence[rev_key]
        else:
            evidence_score, shared_count = 0.0, 0

        # LLM 判断（使用 rule+evidence 回落）
        llm_score_01, explanation = llm_judge(
            company_a["name"], company_b["name"],
            rule_score, evidence_score
        )
        llm_score_100 = round(llm_score_01 * 100, 2)

        # Final score uses: rule 30%, evidence 30%, llm 40%
        final_score = calculate_final_score(
            rule_score, evidence_score, similarity, llm_score_100
        )
        
        # 诊断：收集评分数据
        all_rule_scores.append(rule_score)
        all_evidence_scores.append(evidence_score)
        all_llm_scores.append(llm_score_100)
        all_final_scores.append(final_score)

        # Determine status (thresholds per document section 10.2)
        if final_score > 85:
            status = "auto_merged"
            auto_merged_count += 1
        elif final_score > 60:
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

        # Prepare evidence JSON (extended structure)
        evidence = {
            "rule_score": rule_score,
            "evidence_score": evidence_score,
            "llm_score": llm_score_100,
            "embedding_similarity": round(similarity, 4),
            "sources_a": company_a["sources"],
            "sources_b": company_b["sources"],
            "shared_contacts_count": shared_count,
            "llm_explanation": explanation,
        }

        # Insert into review_candidate
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

        db.execute(insert_sql, {
            "type": "company_merge",
            "a_id": str(company_a["customer_id"]),
            "a_name": company_a["name"],
            "b_id": str(company_b["customer_id"]),
            "b_name": company_b["name"],
            "match": final_score,
            "rule_score": rule_score,
            "evidence_score": evidence_score,
            "llm_score": llm_score_100,
            "evidence_json": json.dumps(evidence, ensure_ascii=False),
            "status": status,
        })

        new_pairs_count += 1

    db.commit()

    # 仅记录关键统计信息
    if all_final_scores:
        logger.info(f"评分统计: 共 {len(all_final_scores)} 个相似对, "
                    f"综合评分 avg={sum(all_final_scores)/len(all_final_scores):.2f}, "
                    f"自动合并: {auto_merged_count}, 待审核: {need_review_count}")

    _dedup_progress["progress"] = 100
    _dedup_progress["details"] = {
        "step_name": "完成",
        "completed": len(similar_pairs),
        "total": len(similar_pairs),
        "message": f"去重任务完成 (处理了 {len(similar_pairs)} 个相似对，新增 {new_pairs_count} 个待审核对)"
    }

    return {
        "total_companies": len(companies),
        "pairs_found": len(similar_pairs),
        "new_pairs_found": new_pairs_count,
        "auto_merged": auto_merged_count,
        "need_review": need_review_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-merge High Confidence Pairs
# ─────────────────────────────────────────────────────────────────────────────

def auto_merge_high_confidence(db: Session, threshold: float = 90.0) -> int:
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
# 公司记录合并
# ─────────────────────────────────────────────────────────────────────────────

def merge_customer_records(
    review_item: Dict[str, Any],
    db: Session
) -> Dict[str, Any]:
    """
    执行两家公司的实际合并操作。

    合并策略：
    1. 确定主公司（优先保留在 dws_customer_360 有记录的一方）
    2. 将从公司的联系人、行为数据等关联到主公司
    3. 更新各 ODS 表中的公司名称引用

    Args:
        review_item: 审核项记录（来自 review_candidate）
        db: 数据库会话

    Returns:
        合并结果摘要
    """
    name_a = review_item.get("candidate_a_name") or review_item.get("candidate_a", "")
    name_b = review_item.get("candidate_b_name") or review_item.get("candidate_b", "")

    if not name_a or not name_b:
        raise ValueError("候选公司名称为空，无法合并")

    # 1. 确定主公司：在 dws_customer_360 中有记录的一方优先
    primary_name, secondary_name = _determine_primary_company(name_a, name_b, db)

    logger.info(f"合并: 主公司={primary_name}, 从公司={secondary_name}")

    merge_stats: Dict[str, int] = {}

    # 2. 更新各方数据源中的公司名称
    for updater, label in [
        (_update_contacts_company_name, "contacts"),
        (_update_behavior_company_name, "behavior"),
        (_update_lead_company_name, "lead"),
        (_update_crm_company_name, "crm"),
    ]:
        try:
            count = updater(secondary_name, primary_name, db)
            merge_stats[label] = count
        except Exception as e:
            logger.warning(f"  更新 {label} 表失败: {e}")
            merge_stats[label] = 0

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


def _update_contacts_company_name(
    old_name: str, new_name: str, db: Session
) -> int:
    """更新 ods_zhique_contact_day 中的公司名称。"""
    update_sql = text("""
        UPDATE ods_zhique_contact_day
        SET related_company = :new_name
        WHERE related_company LIKE :old_name
          AND related_company != :new_name
    """)
    result = db.execute(update_sql, {
        "new_name": new_name,
        "old_name": f"%{old_name}%",
    })
    count = result.rowcount
    if count > 0:
        logger.info(f"  更新联系人表: {count} 条 '{old_name}' -> '{new_name}'")
    return count


def _update_behavior_company_name(
    old_name: str, new_name: str, db: Session
) -> int:
    """更新 ods_zhique_behavior_list_day 中的公司名称。"""
    update_sql = text("""
        UPDATE ods_zhique_behavior_list_day
        SET company_name = :new_name
        WHERE company_name LIKE :old_name
          AND company_name != :new_name
    """)
    result = db.execute(update_sql, {
        "new_name": new_name,
        "old_name": f"%{old_name}%",
    })
    count = result.rowcount
    if count > 0:
        logger.info(f"  更新行为数据表: {count} 条 '{old_name}' -> '{new_name}'")
    return count


def _update_lead_company_name(
    old_name: str, new_name: str, db: Session
) -> int:
    """更新 ods_marketing_lead_day 中的公司名称。"""
    update_sql = text("""
        UPDATE ods_marketing_lead_day
        SET customer_company = :new_name
        WHERE customer_company LIKE :old_name
          AND customer_company != :new_name
    """)
    result = db.execute(update_sql, {
        "new_name": new_name,
        "old_name": f"%{old_name}%",
    })
    count = result.rowcount
    if count > 0:
        logger.info(f"  更新线索表: {count} 条 '{old_name}' -> '{new_name}'")
    return count


def _update_crm_company_name(
    old_name: str, new_name: str, db: Session
) -> int:
    """更新 ods_crm_contact_day 中的公司名称。"""
    update_sql = text("""
        UPDATE ods_crm_contact_day
        SET customer_name = :new_name
        WHERE customer_name LIKE :old_name
          AND customer_name != :new_name
    """)
    result = db.execute(update_sql, {
        "new_name": new_name,
        "old_name": f"%{old_name}%",
    })
    count = result.rowcount
    if count > 0:
        logger.info(f"  更新CRM联系人表: {count} 条 '{old_name}' -> '{new_name}'")
    return count


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
            if row_name not in companies:
                companies[row_name] = {
                    "name": row_name,
                    "customer_id": row_id,
                    "sources": ["dws_customer_360"],
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
        _dedup_progress["results"] = None
        _dedup_progress["details"] = None
        from datetime import datetime
        _dedup_progress["started_at"] = datetime.now().isoformat()

    try:
        # Get a new database session
        from app.database import SessionLocal
        db = SessionLocal()

        try:
            # Generate review pairs（全量模式）
            results = generate_review_pairs(db, incremental=False)

            # Auto-merge high confidence
            auto_merged = auto_merge_high_confidence(db)
            results["auto_merged_final"] = auto_merged

            # 记录本次运行时间，供下次增量去重使用
            from datetime import datetime
            run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_last_dedup_time(run_time)
            results["run_time"] = run_time

            with _dedup_lock:
                _dedup_progress["status"] = "completed"
                _dedup_progress["results"] = results
                _dedup_progress["step"] = "Completed"
                _dedup_progress["progress"] = 100

            logger.info(f"Deduplication completed: {results}")

        finally:
            db.close()

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
