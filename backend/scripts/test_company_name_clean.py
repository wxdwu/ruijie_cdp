"""验证公司名预处理：去符号清洗 + 5 条规则校验。

可独立运行（company_name_clean 仅依赖 re/typing，无项目依赖）。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.common.company_name_clean import (  # noqa: E402
    clean_company_symbols,
    is_valid_company_name,
    preprocess_company_name,
)


def check(raw, expect_clean, expect_valid):
    cleaned = clean_company_symbols(raw)
    valid = is_valid_company_name(cleaned) if cleaned else False
    status = "OK" if (cleaned == expect_clean and valid == expect_valid) else "FAIL"
    print(f"[{status}] raw={raw!r:40} -> clean={cleaned!r:30} valid={valid} "
          f"(expect clean={expect_clean!r} valid={expect_valid})")
    return status == "OK"


cases = [
    # (原始名, 期望清洗结果, 期望合法)
    # ── 去符号（规则1/2）：中文标点/特殊符号应被去除，括号保留且成对 ──
    ("腾讯（深圳）有限公司，", "腾讯（深圳）有限公司", True),
    ("阿里巴巴。", "阿里巴巴", True),
    ("华为技术有限公司；", "华为技术有限公司", True),
    ("锐捷网络（北京）", "锐捷网络（北京）", True),
    ("百度、", "百度", True),
    ("\u3000腾讯\u3000", "腾讯", True),          # 全角空格
    ("A测试B", "A测试B", False),                 # 含 测试 -> 黑名单词（无特征/digit/品牌/英文）
    # ── 合法公司名 ──
    ("锐捷网络", "锐捷网络", True),
    ("腾讯", "腾讯", True),                       # 品牌
    ("360", "360", True),                        # 纯数字≤4
    ("58同城", "58同城", True),                   # 数字+中文（知名数字品牌）
    # ── 数字规则收紧：含阿拉伯数字须为知名数字品牌或数字+单位机构名 ──
    ("资中2中", "资中2中", True),                 # 数字+单位（中=中学缩写）
    ("成都七中", "成都七中", True),               # 中文数字+单位（七=第7中学）
    ("第3中学", "第3中学", True),                 # 第+数字+单位
    ("中关村二小", "中关村二小", True),            # 中文数字+小（第二小学）
    ("中科院2所", "中科院2所", True),             # 数字+所（研究所缩写）
    ("北京101中学", "北京101中学", True),         # 阿拉伯数字+中学
    ("三星电子", "三星电子", True),               # 中文数字品牌（电子为特征词），按普通字符保留
    ("三一集团", "三一集团", True),               # 中文数字品牌（集团为特征词），保留
    ("北京2023科技有限公司", "北京2023科技有限公司", False),  # 含阿拉伯数字但非品牌/单位
    ("测试2024", "测试2024", False),             # 含阿拉伯数字，非品牌/单位
    ("abc123", "abc123", False),                 # 含阿拉伯数字，非品牌/单位
    ("用户456", "用户456", False),               # 含阿拉伯数字，非品牌/单位
    ("Microsoft Corporation", "Microsoft Corporation", True),  # 全英文
    ("AT&T", "ATT", True),                       # & 被去除，仍全英文
    ("华为技术有限公司", "华为技术有限公司", True),
    ("北京分公司", "北京分公司", True),           # 含 公司 特征
    # ── 非法/口语（应判为不合法）──
    ("哈哈", "哈哈", False),
    ("你好", "你好", False),
    ("张三", "张三", False),
    ("unknown", "unknown", True),                # 纯英文像公司（占位词由黑名单过滤层拦截）
    # ── 括号不成对（规则2，应不合法）──
    ("腾讯（深圳有限公司", "腾讯（深圳有限公司", False),
    ("华为技术)有限公司", "华为技术)有限公司", False),
    # ── 连续数字>4（规则3，应不合法）──
    ("13800138000公司", "13800138000公司", False),
    ("北京12345科技有限公司", "北京12345科技有限公司", False),
    # ── 清洗后为空（应丢弃）──
    ("，，，", "", False),
    ("  ", "", False),
    ("@@@", "", False),
]

all_ok = True
for raw, ec, ev in cases:
    if not check(raw, ec, ev):
        all_ok = False

print("\n全部通过" if all_ok else "\n存在失败用例")
sys.exit(0 if all_ok else 1)
