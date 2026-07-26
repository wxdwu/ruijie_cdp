"""ODS 智渠联系人明细表（ods_zhique_contact_detail_day）字段级清洗。

本模块实现"先过滤清洗、再聚合进 DWS"：在 ETL 从 ods_zhique_contact_detail_day
读取 `关联公司` / `姓名` 之后、写入 tmp_icp_customers / dws_contact_mapping 之前，
按字段规则过滤掉明显不是公司名 / 姓名的数据，避免脏数据进入 dws_customer_360、
dws_contact_mapping 等聚合结果。

校验规则（集中在此，便于单测与按需扩展）：
- 关联公司（→ customer_name）：必须是像公司名的字符串。允许含数字的合法机构
  （学校如 第110中学、研究所如 718所、品牌如 58同城/360）；  允许并列/连接符号
  （/ 、 － — ""）以保留多实体机构名（如"三亚中心医院（...、...）"）。
  注意：逗号(,，)、句号(。.)、问号(？?)等明显非法的句子标点，已在源头（写入 tmp_icp_customers 前）
  由 is_valid_company_name 的 _ILLEGAL_PUNCT 硬过滤，避免脏公司名进入聚合结果。
  仅过滤纯序号、手机号、邮箱、广告链接、日期等垃圾信号，以及含不允许的特殊字符
  （点 & 制表符 不可见字符等）、明显非公司名短语（如"兔兔"/"学校"/"医院"）、
  已知脏数据（如"吴磊"）。
- 姓名（→ contact_name）：必须是正常姓名，支持中英文数字混合，但不允许逗号等
  特殊符号、不允许纯数字。

注意：仅作用于 ods_zhique_contact_detail_day，不影响 ods_zhique_contact_day 等其它源。
"""

from __future__ import annotations

import logging
import re

from app.services.etl.common.db import _exec, _exec_query
from app.services.etl.common.constants import BATCH_SIZE

logger = logging.getLogger(__name__)


# ── 公司名字段（`关联公司`）校验 ──────────────────────────────────────────────
# 公司名允许的字符（折中口径）：CJK 汉字、拉丁字母、数字、全/半角括号、空格、连字符(-)，
# 以及合法机构名中常见的并列/连接符号：斜杠(/、／)、顿号(、)、全角逗号(，)、
# 全角杠(－)、破折号(—)、弯引号("")、汉字零(〇)、间隔号(·)。
# 其余（点、&、方头括号、【】、制表符、不可见字符、首尾/内部格式残渣等）经噪声清洗后过滤，
# 详见 _clean_company_for_validation。
_COMPANY_ALLOWED = re.compile(r"^[0-9A-Za-z一-鿿（）() /、，－—“”〇·／\-]+$")
# 公司名必须至少含一个汉字/字母/数字，避免出现纯符号串（如 "-"、"（）"、" "）。
_HAS_SUBSTANCE = re.compile(r"[0-9A-Za-z一-鿿]")
# 明显非法的句子/结构标点：出现在公司名中即视为脏数据，应在写入 tmp_icp_customers 前（源头）过滤。
# 覆盖：逗号(,，)、句号(。.)、问号(？?)、感叹(！!)、分号(；;)、冒号(：:)，以及 @ # % & * = _ ~ 省略号(…)。
# 注意：必须在 _clean_company_for_validation 去噪之前判定，否则脏标点会被先剥掉而漏判。
# 保留多实体机构名所需的合法连接符号：顿号(、)、斜杠(/／)、连字符(-)、破折号(—)、括号（()）、
# 间隔号(·)、汉字零(〇)、弯引号("")。
_ILLEGAL_PUNCT = re.compile(r"[,，。.\?!？！;；:：@#%&*=_~…\u2026]+")

# 纯数字品牌白名单（允许保留，如 360、58 同城关联主体）
_COMPANY_DIGIT_BRAND_OK = {"360", "58"}
# 明显非公司名子串黑名单（包含即过滤，如 "测试"）
_COMPANY_SUBSTR_BLACKLIST = ("测试",)
# 广告 / 垃圾关键词
_GARBAGE_KW = re.compile(r"扣扣|客服电话|出排名|复制此链接|抖音|关键词|官网-腾龙|热线")
_URL_RE = re.compile(r"https?://|://|\.com|\.cn|\.net|douyin|v\.douyin", re.I)
_DATE_RE = re.compile(r"[A-Za-z]+ \d+, \d{4}|月 \d{1,2}, \d{4}|\d{4}年\d{1,2}月\d{1,2}日")
_INVIS_RE = re.compile(r"[\t ­ ­ ­ ­ ­ ­\ufeff]")
# 以纯数字开头、后直接跟 有限公司/公司/集团（无意义编号前缀，如 "123有限公司"）
_DIGIT_PREFIX_COMPANY = re.compile(r"^\d+(有限|公司|集团)")


def _is_company_name_digit_garbage(s: str) -> bool:
    """含数字但属垃圾信号的判定（命中即视为非法公司名）。

    仅覆盖高置信垃圾，保留含数字的合法机构（学校如 第110中学、研究所如 718所、
    医院/部队如 301医院、品牌如 58同城/360/h3c）。
    """
    # 纯数字串（允许少量数字品牌）
    if re.fullmatch(r"\d+", s):
        return s not in _COMPANY_DIGIT_BRAND_OK
    # 长数字（手机号 / 电话 / 邮编，>=7 位连续）
    if re.search(r"\d{7,}", s):
        return True
    # 邮箱 / URL / 广告词 / 日期 / 不可见字符
    if "@" in s or _GARBAGE_KW.search(s) or _URL_RE.search(s) \
            or _DATE_RE.search(s) or _INVIS_RE.search(s):
        return True
    # 数字开头 + "有限公司/公司/集团"（无意义编号前缀）
    if _DIGIT_PREFIX_COMPANY.match(s):
        return True
    return False


# 判定前的噪声清洗：去除首尾及内部的格式残渣（OCR / 复制粘贴引入的标点、引号、不可见字符、
# 以及全角冒号/分号/&/方头括号/尖括号/方括号/句号 等），但保留合法机构名所需的并列/连接符号
# （/ 、 ， － — "" （） 〇 · ／）。仅用于"是否保留"的合法性判定，不修改落库原始值。
# 注意：@ 与 . 故意保留（它们是邮箱 / URL 的垃圾信号，移除会漏判）。
_EDGE_CHARS = (
    " \t\n\r\xa0"
    ".?？!！~_*`'‘’\"\u201c\u201d〓\u002d\uff0d\u2014\u2026"
    "\uff08\uff09()\u3014\u3015[]\u3010\u3011\u3008\u3009\u300a\u300b"
    "\u3001\uff0c\uff1a\uff1b%#&:;\u3000\u3002\uff0e"
    "".join(chr(c) for c in range(0x2000, 0x200C)) + "\ufeff"
)
_INTERNAL_JUNK_RE = re.compile(
    r"[?？!！~*`'‘’〓\u2026\u3014\u3015\[\]\u3010\u3011\u3008\u3009\u300a\u300b"
    r"\uff1a\uff1b%#&:;\xa0\u3002\uff0e\u2000-\u200b\u3000\ufeff]+"
)


def _clean_company_for_validation(s: str) -> str:
    """去除 company 名首尾/内部的噪声字符，用于合法性判定（不改变落库值）。"""
    s = s.strip(_EDGE_CHARS)
    return _INTERNAL_JUNK_RE.sub("", s)


# 姓名允许出现的字符：CJK 汉字、拉丁字母、数字、空白、间隔号（民族姓名如 阿依古丽·买买提）。
_NAME_ALLOWED = re.compile(r"^[0-9A-Za-z一-鿿·\s]+$")

# 明显非公司名的短语黑名单（按需扩展，例如已知脏数据"吴磊"）。大小写不敏感匹配。
_COMPANY_BLACKLIST = {
    "兔兔", "吴磊", "测试", "test", "暂无", "无", "未知", "某某", "null", "none",
    "未填写", "未提供", "保密", "个人", "其他", "其它", "空", "待定", "无公司",
    "未知公司", "公司名", "微信", "扫码", "无名称",
    # 泛称/类别词（非具体公司名，精确匹配，不影响含这些词的合法机构名如 三亚中心医院）
    "学校", "个体", "医院", "学生", "选项一", "选项", "单位", "部门", "科室",
    "公司", "集团", "先生", "女士", "老师", "同学", "朋友", "同事", "领导",
    "客户", "用户", "业主", "家属", "居民", "群众", "团队", "店铺", "商家",
    "门店", "商户",
    # 口语/垃圾短语（非公司名特征，如 激* 系列 spam、各类昵称式叠词）
    "激励激励了", "激凸kkk", "激情戏", "激活", "激萌", "澜起",
    "哈哈", "呵呵", "嘿嘿", "嗯嗯", "哦哦", "天天", "试试", "看看", "刚刚",
    "好好", "滴滴", "嘟嘟", "哥哥", "姐姐", "弟弟", "妹妹",
}

# 明显非姓名的短语黑名单（按需扩展）。大小写不敏感匹配。
_NAME_BLACKLIST = {
    "测试", "test", "未知", "无", "暂无", "null", "none", "未填写", "未提供",
    "保密", "先生", "女士", "同事", "朋友", "无名称",
}

_MAX_COMPANY_LEN = 60
_MAX_NAME_LEN = 20
_MIN_NAME_LEN = 1


def _normalize(value):
    """去除首尾空白；None / 空串归为 None。"""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def is_valid_company_name(value) -> bool:
    """判断 `关联公司` 是否为可接受的客户公司名。

    过滤：空值、超长、纯数字、含不允许的特殊字符、黑名单短语、
    含数字的垃圾信号（纯序号/手机号/邮箱/广告链接/日期等）、
    以及两字完全相同的昵称（如 兔兔、哈哈）。判定前会先做噪声清洗
    （_clean_company_for_validation），但落库值保持原始。
    """
    s = _normalize(value)
    if not s:
        return False
    # 源头硬过滤：含明显非法标点（逗号/句号/问号/感叹/分号/冒号等）即非合法公司名。
    # 必须在 _clean_company_for_validation 去噪之前判定，否则脏标点会被先剥掉而漏判，
    # 导致原始脏字符串（如 "锐捷网络股份有限公司,测试"）仍写入 tmp_icp_customers。
    if _ILLEGAL_PUNCT.search(s):
        return False
    # 判定前清洗 OCR / 复制残渣（不改变落库值）
    s = _clean_company_for_validation(s)
    if not s:
        return False
    if len(s) > _MAX_COMPANY_LEN:
        return False
    # 纯数字（如 "12345"，仅允许 360/58 等数字品牌）
    if re.fullmatch(r"\d+", s):
        return s in _COMPANY_DIGIT_BRAND_OK
    # 含不允许的特殊字符（点、&、方头括号、【】、制表符、不可见字符等）
    if not _COMPANY_ALLOWED.match(s):
        return False
    # 仅由空格/连字符/括号组成、不含任何汉字/字母/数字（如 "-"、"（）"）
    if not _HAS_SUBSTANCE.search(s):
        return False
    # 黑名单短语（精确，大小写不敏感）
    if s.lower() in _COMPANY_BLACKLIST:
        return False
    # 明显非公司名子串（包含即过滤，如 "测试"）
    if any(b in s for b in _COMPANY_SUBSTR_BLACKLIST):
        return False
    # 两字完全相同的昵称（非公司名特征）
    if len(s) == 2 and s[0] == s[1]:
        return False
    # 含数字的垃圾信号（纯序号、手机号、邮箱、广告链接、日期等）
    if _is_company_name_digit_garbage(s):
        return False
    return True


def is_valid_person_name(value) -> bool:
    """判断 `姓名` 是否为可接受的真实姓名。

    支持中英文数字混合；不允许逗号等特殊符号，不允许纯数字，长度 1~20。
    """
    s = _normalize(value)
    if not s:
        return False
    if len(s) < _MIN_NAME_LEN or len(s) > _MAX_NAME_LEN:
        return False
    # 纯数字（如 "13800138000" 作为姓名明显异常）
    if re.fullmatch(r"\d+", s):
        return False
    # 含不允许的特殊字符（逗号、句号、@ 等）
    if not _NAME_ALLOWED.match(s):
        return False
    if s.lower() in _NAME_BLACKLIST:
        return False
    return True


# ── ODS 读取后过滤、再聚合到 DWS 的编排 ──────────────────────────────────────
def read_filtered_companies_from(table: str, column: str, extra_where: str = "") -> list:
    """读取任意 ODS 表的去重公司名字段，按 is_valid_company_name 过滤后返回。

    table / column 为内部常量（非用户输入），直接拼接到 SQL 是安全的。
    供各 customer_name 源（ods_zhique_contact_detail_day.关联公司 等）在写入 tmp_icp_customers 前过滤。
    """
    sql = (
        f"SELECT DISTINCT `{column}` FROM `{table}` "
        f"WHERE `{column}` IS NOT NULL AND `{column}` != '' " + (extra_where or "")
    )
    rows = _exec_query(sql)
    kept = [r[0] for r in rows if r[0] and is_valid_company_name(r[0])]
    skipped = len(rows) - len(kept)
    logger.info(
        "%s.%s 公司名过滤：保留 %d 个，丢弃 %d 个",
        table, column, len(kept), skipped,
    )
    return kept


def read_filtered_zhique_detail_companies() -> list:
    """读取 ods_zhique_contact_detail_day 的去重 `关联公司`，过滤后返回合法公司名列表。

    供锚点表 tmp_icp_customers 构建使用（关联公司 → customer_name → dws_customer_360）。
    """
    return read_filtered_companies_from("ods_zhique_contact_detail_day", "关联公司")


def read_filtered_key_customers() -> list:
    """读取 ods_key_customer 的去重 (key_customer_name + 属性)，按公司名规则过滤。

    返回 5 元组列表：(key_customer_name, customer_name(负责人), department_level3,
    industry_category, attribute)。供 dws_customer_360 / dws_customer_360_temp
    的 Phase 5 重要客户插入使用（先过滤再聚合）。
    """
    rows = _exec_query(
        "SELECT DISTINCT key_customer_name, customer_name, department_level3, "
        "industry_category, attribute "
        "FROM ods_key_customer "
        "WHERE key_customer_name IS NOT NULL AND key_customer_name != ''"
    )
    kept = [r for r in rows if r[0] and is_valid_company_name(r[0])]
    skipped = len(rows) - len(kept)
    logger.info(
        "ods_key_customer 公司名过滤：保留 %d 行，丢弃 %d 行",
        len(kept), skipped,
    )
    return kept


def bulk_insert_key_customers(rows: list, target_table: str) -> int:
    """将已过滤的重要客户批量 INSERT IGNORE 进 dws_customer_360 / dws_customer_360_temp。

    依赖 customer_name 唯一键：已存在的客户由 INSERT IGNORE 跳过（避免重复插入）。
    字段映射：key_customer_name→customer_name，customer_name→owner_name，
    department_level3→region，industry_category→industry，attribute→attribute。
    """
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        placeholders = []
        params = {}
        for j, row in enumerate(batch):
            p = f"k{i}_{j}"
            kcn, owner, region, industry, attr = row
            placeholders.append(f"(:{p}_n, :{p}_o, :{p}_r, :{p}_i, :{p}_a, NOW())")
            params[f"{p}_n"] = kcn
            params[f"{p}_o"] = owner
            params[f"{p}_r"] = region
            params[f"{p}_i"] = industry
            params[f"{p}_a"] = attr
        sql = (
            f"INSERT IGNORE INTO {target_table} "
            "(customer_name, owner_name, region, industry, attribute, updated_at) VALUES "
            + ", ".join(placeholders)
        )
        total += _exec(sql, params)
    return total


def bulk_insert_companies_into_tmp_icp(companies: list) -> int:
    """将已过滤的公司名批量 INSERT IGNORE 进 tmp_icp_customers。"""
    if not companies:
        return 0
    total = 0
    for i in range(0, len(companies), BATCH_SIZE):
        batch = companies[i:i + BATCH_SIZE]
        placeholders = [f":c{i}_{j}" for j in range(len(batch))]
        params = {f"c{i}_{j}": name for j, name in enumerate(batch)}
        sql = (
            "INSERT IGNORE INTO tmp_icp_customers (customer_name) VALUES "
            + ", ".join(f"({p})" for p in placeholders)
        )
        total += _exec(sql, params)
    return total


def read_filtered_zhique_detail_contacts(
    time_filter_sql: str = "", time_filter_params: dict | None = None
) -> list:
    """读取 ods_zhique_contact_detail_day，按 `关联公司` + `姓名` 过滤后返回保留行。

    返回 6 元组列表：(关联公司, 姓名, 手机号, 邮箱, 部门, 职务)。
    任一声段不合法则整行丢弃（关联公司 → customer_name，姓名 → contact_name）。

    time_filter_sql / time_filter_params：增量同步时传入 `time` 水位过滤子句
    （如 "AND d.`time` > :watermark"）及其参数。
    """
    sql = (
        "SELECT `关联公司`, `姓名`, `手机号`, `邮箱`, `部门`, `职务` "
        "FROM ods_zhique_contact_detail_day d "
        "WHERE d.`关联公司` IS NOT NULL AND d.`关联公司` != '' "
        + (time_filter_sql or "")
    )
    rows = _exec_query(sql, time_filter_params or {})
    kept = []
    skipped = 0
    for r in rows:
        company, name = r[0], r[1]
        if is_valid_company_name(company) and is_valid_person_name(name):
            kept.append(r)
        else:
            skipped += 1
    logger.info(
        "zhique_detail 联系人过滤：保留 %d 行，丢弃 %d 行",
        len(kept), skipped,
    )
    return kept


def bulk_write_contact_mapping(
    rows: list, *, target_table: str, sync_batch_id: int | None = None
) -> int:
    """将已过滤的联系人行批量写入 contact_mapping 表。

    - 全量同步：target_table="dws_contact_mapping"，INSERT IGNORE（不写 sync_batch_id）。
    - 增量同步：target_table="dws_contact_mapping_temp"，INSERT ... ON DUPLICATE KEY UPDATE
      （写 sync_batch_id，主键为 (customer_name, mobile)）。
    """
    if not rows:
        return 0
    use_upsert = sync_batch_id is not None
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        placeholders = []
        params = {}
        for j, row in enumerate(batch):
            p = f"r{i}_{j}"
            company, name, mobile, email, dept, pos = row
            if use_upsert:
                placeholders.append(
                    f"(:{p}_c, :{p}_n, :{p}_m, :{p}_e, :{p}_d, :{p}_o, "
                    f"'zhique_detail', NOW(), :{p}_b)"
                )
                params[f"{p}_b"] = sync_batch_id
            else:
                placeholders.append(
                    f"(:{p}_c, :{p}_n, :{p}_m, :{p}_e, :{p}_d, :{p}_o, "
                    f"'zhique_detail', NOW())"
                )
            params[f"{p}_c"] = company
            params[f"{p}_n"] = name
            params[f"{p}_m"] = mobile
            params[f"{p}_e"] = email
            params[f"{p}_d"] = dept
            params[f"{p}_o"] = pos
        if use_upsert:
            sql = (
                f"INSERT INTO {target_table} "
                "(customer_name, contact_name, mobile, email, department, "
                "position, source_table, etl_time, sync_batch_id) VALUES "
                + ", ".join(placeholders)
                + " ON DUPLICATE KEY UPDATE "
                "contact_name = VALUES(contact_name), email = VALUES(email), "
                "department = VALUES(department), position = VALUES(position), "
                "etl_time = VALUES(etl_time), sync_batch_id = VALUES(sync_batch_id)"
            )
        else:
            sql = (
                f"INSERT IGNORE INTO {target_table} "
                "(customer_name, contact_name, mobile, email, department, "
                "position, source_table, etl_time) VALUES "
                + ", ".join(placeholders)
            )
        total += _exec(sql, params)
    return total
