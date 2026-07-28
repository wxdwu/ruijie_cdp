"""临时分析脚本：连库只读抽样，辅助设计白/黑名单规则并定位审核队列错位。

使用：python scripts/analyze_cdp.py
"""
import pymysql
import re

conn = pymysql.connect(
    host="192.168.159.22",
    port=33307,
    user="root",
    password="t2yccidfsbseang1",
    database="app_cdp",
    charset="utf8mb4",
)
cur = conn.cursor(pymysql.cursors.DictCursor)

print("=" * 70)
print("1) review_candidate 概况 + 样例")
print("=" * 70)
cur.execute("SELECT COUNT(*) c FROM review_candidate")
print("review_candidate total:", cur.fetchone()["c"])
cur.execute(
    "SELECT candidate_a_id, candidate_a_name, candidate_b_id, candidate_b_name, "
    "match_score FROM review_candidate ORDER BY match_score DESC LIMIT 20"
)
for r in cur.fetchall():
    print(r)

print("-" * 70)
print("candidate_a_id 分布 (TOP10):")
cur.execute(
    "SELECT candidate_a_id, COUNT(*) c FROM review_candidate "
    "GROUP BY candidate_a_id ORDER BY c DESC LIMIT 10"
)
for r in cur.fetchall():
    print("   ", r)

print("=" * 70)
print("2) candidate 名称在 dws_customer_360 的命中率")
print("=" * 70)
cur.execute(
    "SELECT candidate_a_name, candidate_b_name FROM review_candidate LIMIT 500"
)
names = set()
for r in cur.fetchall():
    if r["candidate_a_name"]:
        names.add(r["candidate_a_name"])
    if r["candidate_b_name"]:
        names.add(r["candidate_b_name"])
print("参与审核的去重候选名数量:", len(names))
cur.execute("SELECT customer_name FROM dws_customer_360")
c360 = set(r["customer_name"] for r in cur.fetchall())
exact = sum(1 for n in names if n in c360)
print("精确命中 dws_customer_360 的候选名:", exact, "/", len(names))

print("=" * 70)
print("3) dws_customer_360.customer_name 非法/可疑分布")
print("=" * 70)
cur.execute("SELECT customer_name FROM dws_customer_360")
all_names = [r["customer_name"] for r in cur.fetchall()]
print("dws_customer_360 总数:", len(all_names))

checks = {
    "含@": r"@",
    "含URL": r"(http|www\.|\.com|\.cn|\.net)",
    "纯数字": r"^\d+$",
    "含test/未知/null等": r"(test|测试|未知|unknow|null|none|待定|tbd|xxx|无)",
    "含非字母数字中文符号": r"[^\w\u4e00-\u9fff]",
    "长度<2": None,
    "长度>40": None,
}
for label, pat in checks.items():
    if pat is None:
        continue
    cnt = sum(1 for n in all_names if re.search(pat, n, re.I))
    print(f"  {label}: {cnt}  ({round(cnt / len(all_names) * 100, 2)}%)")

cnt_short = sum(1 for n in all_names if len(n) < 2)
cnt_long = sum(1 for n in all_names if len(n) > 40)
print(f"  长度<2: {cnt_short}")
print(f"  长度>40: {cnt_long}")

valid = (
    r"(公司|集团|股份|有限|企业|厂|局|所|院|银行|保险|证券|医院|学校|大学|学院|"
    r"电视台|出版社|报社|协会|基金会|合作社|商行|门店|中心|科技|网络|技术|实业|"
    r"控股|投资|管理|咨询|电子|信息|能源|医疗|生物|教育|文化|传媒|贸易|物流|建设|"
    r"工程|房地产|置业|酒店|旅游|食品|服饰|汽车|机械|化工|材料|环境|智能|数据|"
    r"软件|通信|金融|基金|租赁|供应链|电子商务)"
)
cnt_valid = sum(1 for n in all_names if re.search(valid, n))
print(f"  含企业特征词: {cnt_valid} / {len(all_names)} ({round(cnt_valid/len(all_names)*100,2)}%)")

person = [
    n for n in all_names
    if not re.search(valid, n) and re.fullmatch(r"[\u4e00-\u9fff]{2,4}", n)
]
print(f"  疑似人名(2-4中文字无特征词): {len(person)}")
print("   样本:", person[:40])

print("  样本[含@]:", [n for n in all_names if "@" in n][:10])
print("  样本[含URL]:", [n for n in all_names if re.search(r"(http|www\.|\.com|\.cn)", n, re.I)][:10])
print("  样本[含test/未知]:", [n for n in all_names if re.search(r"(test|测试|未知|unknow|null|none|待定|tbd|xxx|无)", n, re.I)][:25])
print("  样本[符号]:", [n for n in all_names if re.search(r"[^\w\u4e00-\u9fff]", n)][:25])
print("  样本[纯数字]:", [n for n in all_names if re.fullmatch(r"\d+", n)][:10])

conn.close()
