"""验证白/黑名单筛选规则在 dws_customer_360 上的实际效果（用 MySQL REGEXP）。"""
import pymysql

# 白/黑名单规则统一从独立 Python 模块引入，与运行时保持一致（不再读取数据库表）。
from app.services.common.company_whitelist import (
    VALID_COMPANY_REGEX,
    VALID_WHITELIST_PATTERNS,
)
from app.services.common.company_blacklist import VALID_BLACKLIST_PATTERNS

wl = "|".join(VALID_WHITELIST_PATTERNS)
BLACKLIST = list(VALID_BLACKLIST_PATTERNS)
bl = "|".join(BLACKLIST)

conn = pymysql.connect(
    host="192.168.159.22", port=33307, user="root",
    password="t2yccidfsbseang1", database="app_cdp", charset="utf8mb4",
)
cur = conn.cursor(pymysql.cursors.DictCursor)

sql = f"""
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN (contact_count>0 OR interaction_count_total>0) THEN 1 ELSE 0 END) AS has_data,
  SUM(CASE WHEN customer_name REGEXP %s THEN 1 ELSE 0 END) AS wl_hit,
  SUM(CASE WHEN customer_name REGEXP %s THEN 1 ELSE 0 END) AS bl_hit,
  SUM(CASE WHEN NOT (contact_count>0 OR interaction_count_total>0)
            AND NOT (customer_name REGEXP %s)
            AND (customer_name REGEXP %s) THEN 1 ELSE 0 END) AS will_remove
FROM dws_customer_360
"""
cur.execute(sql, (wl, bl, wl, bl))
print(cur.fetchone())

print("-" * 70)
print("将被剔除（命中黑名单且无数据非白名单）的抽样：")
cur.execute(f"""
SELECT customer_name FROM dws_customer_360
WHERE NOT (contact_count>0 OR interaction_count_total>0)
  AND NOT (customer_name REGEXP %s)
  AND (customer_name REGEXP %s)
LIMIT 30
""", (wl, bl))
for r in cur.fetchall():
    print("   ", r["customer_name"])

print("-" * 70)
print("不确定（非白名单且非黑名单）抽样——默认保留：")
cur.execute(f"""
SELECT customer_name FROM dws_customer_360
WHERE NOT (customer_name REGEXP %s)
  AND NOT (customer_name REGEXP %s)
LIMIT 25
""", (wl, bl))
for r in cur.fetchall():
    print("   ", r["customer_name"])

conn.close()
