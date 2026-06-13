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

import hashlib
import json
import logging
import httpx
import re
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def compute_embeddings_batch(names: List[str]) -> List[np.ndarray]:
    """
    Compute embeddings for a batch of company names using real API.
    Results cached in SQLite to avoid recomputation.

    Args:
        names: List of company names

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
        return embeddings

    # Compute real embeddings for uncached names via API
    api_key = settings.LLM_API_KEY
    base_url = settings.LLM_BASE_URL

    if not api_key or not base_url:
        logger.warning("LLM API not configured, falling back to rule-based embedding")
        # Fallback: use normalized name hash (deterministic but meaningful)
        for idx in uncached_indices:
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
        return embeddings

    # Call real embedding API in batches
    batch_size = 100
    resolved_url = f"{base_url.rstrip('/')}/embeddings"

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

                logger.info(f"  Embedded batch {batch_start // batch_size + 1}: "
                          f"{len(batch_names)} names")

        except Exception as e:
            logger.warning(f"Embedding API call failed for batch {e}, "
                          f"falling back to hash embedding")
            for idx in batch_indices:
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


def find_similar_pairs(
    embeddings: List[np.ndarray],
    names: List[str],
    threshold: float = 0.85
) -> List[Tuple[int, int, float]]:
    """
    Find similar name pairs using cosine similarity.

    Args:
        embeddings: List of embedding vectors
        names: List of company names
        threshold: Minimum similarity threshold

    Returns:
        List of (index_a, index_b, similarity_score)
    """
    pairs: List[Tuple[int, int, float]] = []
    n = len(embeddings)

    # Build a lookup for normalized names to avoid exact duplicates first
    name_to_indices: Dict[str, List[int]] = defaultdict(list)
    for i, name in enumerate(names):
        normalized = normalize_company_name(name)
        if normalized:
            name_to_indices[normalized].append(i)

    # Exact normalized matches get high priority
    for normalized, indices in name_to_indices.items():
        if len(indices) > 1:
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    pairs.append((indices[i], indices[j], 0.98))

    # Compute cosine similarity for all other pairs
    for i in range(n):
        for j in range(i + 1, n):
            # Skip if already added as exact match
            norm_i = normalize_company_name(names[i])
            norm_j = normalize_company_name(names[j])
            if norm_i == norm_j and norm_i:
                continue

            similarity = cosine_similarity(embeddings[i], embeddings[j])
            if similarity >= threshold:
                pairs.append((i, j, similarity))

    # Sort by similarity descending
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
    - Levenshtein distance
    - Substring containment
    - Common prefix/suffix
    - Shared tokens

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
        scores.append(lev_score * 0.4)

    # 2. Substring containment
    if norm_a in norm_b:
        containment = len(norm_a) / len(norm_b) * 100
        scores.append(containment * 0.3)
    elif norm_b in norm_a:
        containment = len(norm_b) / len(norm_a) * 100
        scores.append(containment * 0.3)
    else:
        # Check for common substrings of significant length
        common_chars = len(set(norm_a) & set(norm_b))
        total_chars = len(set(norm_a) | set(norm_b))
        if total_chars > 0:
            jaccard = common_chars / total_chars * 100
            scores.append(jaccard * 0.2)

    # 3. Token-based similarity
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    if tokens_a and tokens_b:
        common_tokens = len(tokens_a & tokens_b)
        token_score = common_tokens / max(len(tokens_a), len(tokens_b)) * 100
        scores.append(token_score * 0.3)

    # Combine scores
    final_score = min(100.0, sum(scores))

    return round(final_score, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Evidence-based Score (Shared Contacts)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_evidence_score(name_a: str, name_b: str, db: Session) -> float:
    """
    Calculate evidence score based on shared contacts (phone/email).

    Args:
        name_a: First company name
        name_b: Second company name
        db: Database session

    Returns:
        Score between 0 and 100
    """
    evidence_score = 0.0
    evidence_count = 0

    # Check for shared phones
    phone_sql = text("""
        SELECT COUNT(DISTINCT c1.phone) as shared_phones
        FROM ods_zhique_contact_day c1
        JOIN ods_zhique_contact_day c2 ON c1.phone = c2.phone
        WHERE c1.company_name LIKE :name_a
          AND c2.company_name LIKE :name_b
          AND c1.phone IS NOT NULL AND c1.phone != ''
    """)

    # Check for shared emails
    email_sql = text("""
        SELECT COUNT(DISTINCT c1.email) as shared_emails
        FROM ods_zhique_contact_day c1
        JOIN ods_zhique_contact_day c2 ON c1.email = c2.email
        WHERE c1.company_name LIKE :name_a
          AND c2.company_name LIKE :name_b
          AND c1.email IS NOT NULL AND c1.email != ''
    """)

    try:
        phone_result = db.execute(
            phone_sql, {"name_a": f"%{name_a}%", "name_b": f"%{name_b}%"}
        ).scalar() or 0

        email_result = db.execute(
            email_sql, {"name_a": f"%{name_a}%", "name_b": f"%{name_b}%"}
        ).scalar() or 0

        # Score based on shared contacts
        # 1 shared phone/email = 20 points
        # Max 100 points
        shared_contacts = phone_result + email_result
        if shared_contacts > 0:
            evidence_score = min(100.0, shared_contacts * 25.0)
            evidence_count = shared_contacts

    except Exception as e:
        logger.warning(f"Error calculating evidence score: {e}")
        # Default: no evidence
        evidence_score = 0.0

    return round(evidence_score, 2), evidence_count


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
    final_score = (
        rule_score * 0.3 +
        evidence_score * 0.3 +
        llm_score * 0.4
    )

    return round(min(100.0, final_score), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Fetch Company Names
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_company_names(db: Session) -> List[Dict[str, Any]]:
    """
    Fetch all unique company names from all sources.

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
    companies: Dict[str, Dict[str, Any]] = {}

    # Source 1: dws_customer_360
    try:
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
        logger.info(f"Found {len(result1)} companies from dws_customer_360")
    except Exception as e:
        logger.warning(f"Error fetching from dws_customer_360: {e}")

    # Source 2: ods_zhique_behavior_list_day
    try:
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
        logger.info(f"Found {len(result2)} companies from ods_zhique_behavior_list_day")
    except Exception as e:
        logger.warning(f"Error fetching from ods_zhique_behavior_list_day: {e}")

    # Source 3: ods_marketing_lead_day
    try:
        sql3 = text("""
            SELECT DISTINCT company_name
            FROM ods_marketing_lead_day
            WHERE company_name IS NOT NULL AND company_name != ''
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
        logger.info(f"Found {len(result3)} companies from ods_marketing_lead_day")
    except Exception as e:
        logger.warning(f"Error fetching from ods_marketing_lead_day: {e}")

    # Source 4: ods_zhique_contact_day
    try:
        sql4 = text("""
            SELECT DISTINCT company_name
            FROM ods_zhique_contact_day
            WHERE company_name IS NOT NULL AND company_name != ''
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
        logger.info(f"Found {len(result4)} companies from ods_zhique_contact_day")
    except Exception as e:
        logger.warning(f"Error fetching from ods_zhique_contact_day: {e}")

    # Source 5: ods_crm_contact_day
    try:
        sql5 = text("""
            SELECT DISTINCT company_name
            FROM ods_crm_contact_day
            WHERE company_name IS NOT NULL AND company_name != ''
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
        logger.info(f"Found {len(result5)} companies from ods_crm_contact_day")
    except Exception as e:
        logger.warning(f"Error fetching from ods_crm_contact_day: {e}")

    # Add some test data if no companies found
    if not companies:
        test_companies = [
            "阿里巴巴集团控股有限公司", "阿里巴巴(中国)有限公司",
            "腾讯控股有限公司", "腾讯科技(深圳)有限公司",
            "字节跳动有限公司", "北京字节跳动科技有限公司",
            "百度在线网络技术(北京)有限公司", "百度公司",
            "京东集团", "北京京东世纪贸易有限公司",
            "美团点评", "北京三快在线科技有限公司",
            "小米科技有限责任公司", "小米集团",
            "华为技术有限公司", "华为投资控股有限公司",
        ]
        for i, name in enumerate(test_companies):
            companies[name] = {
                "name": name,
                "customer_id": f"C{i:03d}",
                "sources": ["test_data"]
            }

    result = list(companies.values())
    logger.info(f"Total unique companies found: {len(result)}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Generate Review Pairs
# ─────────────────────────────────────────────────────────────────────────────

def generate_review_pairs(db: Session) -> Dict[str, Any]:
    """
    Generate all potential duplicate pairs and insert into dws_review_queue.

    Args:
        db: Database session

    Returns:
        Statistics about the deduplication run
    """
    global _dedup_progress

    # Step 1: Fetch all company names
    _dedup_progress["step"] = "Fetching company names"
    _dedup_progress["progress"] = 10
    companies = fetch_all_company_names(db)
    names = [c["name"] for c in companies]

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
    embeddings = compute_embeddings_batch(names)

    # Step 3: Find similar pairs
    _dedup_progress["step"] = "Finding similar pairs"
    _dedup_progress["progress"] = 50
    similar_pairs = find_similar_pairs(embeddings, names, threshold=0.70)

    # Step 4: Score and insert into review queue
    _dedup_progress["step"] = "Scoring and inserting pairs"
    _dedup_progress["progress"] = 70

    new_pairs_count = 0
    auto_merged_count = 0
    need_review_count = 0

    for idx_a, idx_b, similarity in similar_pairs:
        company_a = companies[idx_a]
        company_b = companies[idx_b]

        # Calculate scores
        rule_score = calculate_rule_score(company_a["name"], company_b["name"])
        evidence_score, shared_count = calculate_evidence_score(
            company_a["name"], company_b["name"], db
        )

        # LLM judgment (uses empty api_key by default → rule+evidence fallback)
        llm_score_01, explanation = llm_judge(
            company_a["name"], company_b["name"],
            rule_score, evidence_score
        )
        llm_score_100 = round(llm_score_01 * 100, 2)

        # Final score uses: rule 30%, evidence 30%, llm 40%
        final_score = calculate_final_score(
            rule_score, evidence_score, similarity, llm_score_100
        )

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

        # Check if pair already exists in dws_review_queue
        check_sql = text("""
            SELECT COUNT(*) FROM dws_review_queue
            WHERE (candidate_a = :a_name AND candidate_b = :b_name)
               OR (candidate_a = :b_name AND candidate_b = :a_name)
        """)

        exists = db.execute(check_sql, {
            "a_name": company_a["name"],
            "b_name": company_b["name"]
        }).scalar() or 0

        if exists > 0:
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

        # Insert into dws_review_queue
        insert_sql = text("""
            INSERT INTO dws_review_queue
            (review_type, candidate_a, candidate_b, match_score, evidence, status)
            VALUES (:type, :a_name, :b_name, :match, :evidence_json, :status)
        """)

        db.execute(insert_sql, {
            "type": "company_merge",
            "a_name": company_a["name"],
            "b_name": company_b["name"],
            "match": final_score,
            "evidence_json": json.dumps(evidence, ensure_ascii=False),
            "status": status,
        })

        new_pairs_count += 1

    db.commit()

    _dedup_progress["progress"] = 100

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
        UPDATE dws_review_queue
        SET status = 'auto_merged',
            reviewer = 'system',
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

    try:
        # Get a new database session
        from app.database import SessionLocal
        db = SessionLocal()

        try:
            # Generate review pairs
            results = generate_review_pairs(db)

            # Auto-merge high confidence
            auto_merged = auto_merge_high_confidence(db)
            results["auto_merged_final"] = auto_merged

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
