"""
公司名预处理：去除异常符号 + 合法性校验。

用于「公司名从数据库读出后」的预处理，确保客户管理界面 / 去重审核队列不出现
异常符号或口语化脏数据。

正常公司名遵循的规则：
（1）可包含中文、英文、数字、空格、匹配的左右括号；
（2）其他非法字符不存在，左右括号必须成对（不能只有一个）；
（3）数字连续一般不超过 4 个（如 360、58同城 合法；5 位及以上视为手机号/ID 片段）；
（4）支持全英文的公司名；
（5）应是合法且可查到的公司名，而非口语（哈哈、你好 等应被剔除）。
    数字规则收紧：含阿拉伯数字的名称必须是（知名数字品牌，如 58同城/360）或
    （数字+单位机构名，如 资中2中/成都七中/第3中学），否则过滤；中文数字品牌
    （三星/三一等）按普通字符处理，不触发该门槛。
"""

from __future__ import annotations

import re
from typing import Optional

# 合法公司名规则统一从 company_whitelist 模块引入，避免多处重复定义导致漂移。
from app.services.common.company_whitelist import (
    VALID_COMPANY_REGEX,
    VALID_WHITELIST_PATTERNS,
    KNOWN_DIGIT_BRAND_PATTERN,
    DIGIT_UNIT_PATTERN,
)

# 允许出现在公司名中的字符：中文、英文字母、数字、空格、左右括号（半角/全角）。
# 其他字符（中文标点、特殊符号、emoji 等）一律视为非法符号，清洗时去除。
_ALLOWED_CHAR_RE = re.compile(r"[^一-龥A-Za-z0-9 （）()]")

# 清洗后折叠多余空格
_WS_RE = re.compile(r"\s+")

# 连续数字上限（5 位及以上视为手机号/ID 片段等非法内容）
_DIGIT_RUN_RE = re.compile(r"[0-9]{5,}")

# 全英文/数字公司名（允许英文公司名中常见的 . & - 空格；清洗时会去除符号，
# 此处仅用于「像公司」判定，避免把纯英文公司名误判为非法）。
_ENGLISH_NAME_RE = re.compile(r"^[A-Za-z0-9 .&\-]+$")

# 合法公司名的特征词（与白名单通用规则同源，单一来源 company_whitelist）
_COMPANY_FEATURE_RE = re.compile(VALID_COMPANY_REGEX)

# 知名品牌特例（无特征词但确为合法公司），取自白名单第 2 条特例规则
_BRAND_RE = re.compile(VALID_WHITELIST_PATTERNS[1])

# 数字规则收紧：含阿拉伯数字的名称，必须命中以下两类之一才视为合法公司名，
# 否则按非法过滤。中文数字（三星/三一等）按普通字符处理，不触发此门槛。
# （1）知名数字品牌，如 58同城 / 360 / 3M / 7天 / 21世纪 等；
# （2）数字 + 单位 机构名，如 资中2中 / 成都七中 / 第3中学 / 中科院2所 等。
_DIGIT_BRAND_RE = re.compile(KNOWN_DIGIT_BRAND_PATTERN)
_DIGIT_UNIT_RE = re.compile(DIGIT_UNIT_PATTERN)

# 阿拉伯数字（数字规则门槛仅对阿拉伯数字生效，中文数字视为普通字符）
_ARABIC_DIGIT_RE = re.compile(r"[0-9]")


def clean_company_symbols(name: str) -> str:
    """去除公司名中的异常符号（中文标点及其他非法字符），返回清洗后的名称。

    保留：中文、英文字母、数字、空格、左右括号（半角/全角）。
    去除后折叠空格并去首尾空白；若结果为空串则返回空串。
    """
    if not name or not isinstance(name, str):
        return ""
    cleaned = _ALLOWED_CHAR_RE.sub("", name)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned


def _parens_balanced(name: str) -> bool:
    """左右括号必须成对出现（半角与全角分别配对），不能只有一个。"""
    if name.count("(") != name.count(")"):
        return False
    if name.count("（") != name.count("）"):
        return False
    return True


def _looks_like_company(name: str) -> bool:
    """规则(5)：公司名应像合法公司而非口语（哈哈/你好等）。

    数字规则收紧：名称含阿拉伯数字时，必须是（知名数字品牌）或（数字+单位机构名），
    否则视为非法公司名。其余名称按原规则判定（企业特征词 / 纯英文数字 / 知名品牌）。

    说明：中文数字（三星、三一等）按普通字符处理，不触发数字门槛，仍走特征词/品牌判定。
    """
    # 数字 + 单位机构名（阿拉伯或中文数字紧邻单位词，或「第+数字+单位」），直接放行
    if _DIGIT_UNIT_RE.search(name):
        return True
    # 知名数字品牌（58同城 / 360 / 3M / 7天 / 21世纪 等），直接放行
    if _DIGIT_BRAND_RE.search(name):
        return True
    # 含阿拉伯数字但既非数字品牌也非数字+单位 -> 不似合法公司，过滤
    if _ARABIC_DIGIT_RE.search(name):
        return False
    # 其余：含企业特征词 / 纯英文数字 / 命中知名品牌 -> 允许
    if _COMPANY_FEATURE_RE.search(name):
        return True
    if _ENGLISH_NAME_RE.match(name):
        return True
    if _BRAND_RE.match(name):
        return True
    return False


def is_valid_company_name(name: str) -> bool:
    """校验清洗后的公司名是否符合 5 条规则：

    (1) 仅含中文/英文/数字/空格/匹配括号；(2) 括号成对；
    (3) 连续数字不超过 4；(4) 支持全英文；(5) 像合法公司而非口语。
    """
    if not name:
        return False
    # (1) 字符集（清洗后理论上已满足，这里兜底）
    if not re.fullmatch(r"[一-龥A-Za-z0-9 （）()]*", name):
        return False
    # (2) 括号成对
    if not _parens_balanced(name):
        return False
    # (3) 连续数字不超过 4
    if _DIGIT_RUN_RE.search(name):
        return False
    # (4) 全英文已在 (1) 允许；(5) 像公司
    if not _looks_like_company(name):
        return False
    return True


def preprocess_company_name(name: str) -> Optional[str]:
    """预处理入口：清洗 → 非空 → 合法校验。

    返回清洗后的合法公司名；若清洗后为空或非法则返回 None（调用方应丢弃该记录）。
    """
    cleaned = clean_company_symbols(name)
    if not cleaned:
        return None
    if not is_valid_company_name(cleaned):
        return None
    return cleaned
