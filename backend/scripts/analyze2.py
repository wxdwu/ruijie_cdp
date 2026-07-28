"""验证 review_candidate 的 id 与 name 是否对应 360 表，并查看 360 表结构。"""
import pymysql

conn = pymysql.connect(
    host="192.168.159.22", port=33307, user="root",
    password="t2yccidfsbseang1", database="app_cdp", charset="utf8mb4",
)
cur = conn.cursor(pymysql.cursors.DictCursor)

print("=" * 70)
print("dws_customer_360 表结构")
print("=" * 70)
cur.execute("DESCRIBE dws_customer_360")
for r in cur.fetchall():
    print(r)

print("=" * 70)
print("360 表 customer_name 是否唯一？")
print("=" * 70)
cur.execute("SELECT COUNT(*) c FROM dws_customer_360")
total = cur.fetchone()["c"]
cur.execute("SELECT COUNT(DISTINCT customer_name) c FROM dws_customer_360")
distinct = cur.fetchone()["c"]
print("总行数:", total, " 去重 customer_name:", distinct, " 重复行:", total - distinct)

C = " COLLATE utf8mb4_0900_ai_ci"

print("=" * 70)
print("review_candidate: candidate_a_id 对应的真实 name 是否 == candidate_a_name ?")
print("=" * 70)
cur.execute(f"""
    SELECT
        SUM(CASE WHEN c.customer_name{C} <=> rc.candidate_a_name{C} THEN 0 ELSE 1 END) AS a_mismatch,
        SUM(CASE WHEN c2.customer_name{C} <=> rc.candidate_b_name{C} THEN 0 ELSE 1 END) AS b_mismatch,
        SUM(CASE WHEN c.id IS NULL THEN 1 ELSE 0 END) AS a_id_null,
        COUNT(*) AS total
    FROM review_candidate rc
    LEFT JOIN dws_customer_360 c  ON c.id  = rc.candidate_a_id
    LEFT JOIN dws_customer_360 c2 ON c2.id = rc.candidate_b_id
""")
print(cur.fetchone())

print("-" * 70)
print("错位的样例:")
cur.execute(f"""
    SELECT rc.candidate_a_id, rc.candidate_a_name, c.customer_name AS real_a_name,
           rc.candidate_b_id, rc.candidate_b_name, c2.customer_name AS real_b_name
    FROM review_candidate rc
    LEFT JOIN dws_customer_360 c  ON c.id  = rc.candidate_a_id
    LEFT JOIN dws_customer_360 c2 ON c2.id = rc.candidate_b_id
    WHERE c.customer_name{C} <=> rc.candidate_a_name{C} IS FALSE
       OR c2.customer_name{C} <=> rc.candidate_b_name{C} IS FALSE
    LIMIT 15
""")
for r in cur.fetchall():
    print(r)

print("=" * 70)
print("candidate_a_name 在 360 中的 id 是否 == candidate_a_id")
print("=" * 70)
cur.execute(f"""
    SELECT
        SUM(CASE WHEN c_by_name.id = rc.candidate_a_id THEN 0 ELSE 1 END) AS name_id_mismatch
    FROM review_candidate rc
    LEFT JOIN dws_customer_360 c_by_name
        ON c_by_name.customer_name{C} = rc.candidate_a_name{C}
""")
print(cur.fetchone())

conn.close()
