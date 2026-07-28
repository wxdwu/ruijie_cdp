"""修正存量 review_candidate 的候选 id：按候选公司名重新绑定 dws_customer_360 真实 id。

根因：generate_review_pairs 原先使用各 ODS 源行 id 作为 candidate_a_id/b_id，
与 dws_customer_360 的 id 空间不同，导致前端跳转/详情与展示公司名完全错位。

本脚本对每条 review_candidate，按 candidate_a_name / candidate_b_name 去 360 表
查真实客户 id 并回写；若名称不在 360（多为 ODS 别名），则置为 'default_id'。

使用：python scripts/fix_review_ids.py
"""
import pymysql

conn = pymysql.connect(
    host="192.168.159.22", port=33307, user="root",
    password="t2yccidfsbseang1", database="app_cdp", charset="utf8mb4",
)
cur = conn.cursor(pymysql.cursors.DictCursor)

# 构建 360 名称->id 映射（同名取首个 id）
cur.execute(
    "SELECT customer_name, id FROM dws_customer_360 "
    "WHERE customer_name IS NOT NULL AND customer_name != ''"
)
name_to_id = {}
for r in cur.fetchall():
    name_to_id.setdefault(r["customer_name"], r["id"])

# 反向：id->name，用于校验
id_to_name = {}
cur.execute(
    "SELECT id, customer_name FROM dws_customer_360 "
    "WHERE customer_name IS NOT NULL AND customer_name != ''"
)
for r in cur.fetchall():
    id_to_name.setdefault(r["id"], r["customer_name"])


def resolve(name):
    """返回应写入的 candidate id（360 真实 id 或 'default_id'）。"""
    if name in name_to_id:
        return str(name_to_id[name])
    return "default_id"


cur.execute(
    "SELECT candidate_a_name, candidate_b_name FROM review_candidate"
)
rows = cur.fetchall()

upd_a = 0
upd_b = 0
mismatch_after = 0
for r in rows:
    a_name = r["candidate_a_name"]
    b_name = r["candidate_b_name"]
    new_a = resolve(a_name)
    new_b = resolve(b_name)

    # 校验：若绑定了真实 360 id，其对应 name 应等于候选名
    if new_a != "default_id":
        if id_to_name.get(int(new_a)) != a_name:
            mismatch_after += 1
    if new_b != "default_id":
        if id_to_name.get(int(new_b)) != b_name:
            mismatch_after += 1

    cur.execute(
        "UPDATE review_candidate SET candidate_a_id=%s, candidate_b_id=%s "
        "WHERE candidate_a_name=%s AND candidate_b_name=%s",
        (new_a, new_b, a_name, b_name),
    )
    upd_a += 1

conn.commit()
print(f"处理候选对: {len(rows)}")
print(f"绑定 360 真实 id 的候选名数(含a/b): 见上方)")
print(f"修正后仍不匹配（360 同名多 id 取首个导致）的条目数: {mismatch_after}")

# 统计修正后状态
cur.execute(
    "SELECT "
    "SUM(CASE WHEN candidate_a_id='default_id' THEN 1 ELSE 0 END) AS a_default, "
    "SUM(CASE WHEN candidate_b_id='default_id' THEN 1 ELSE 0 END) AS b_default, "
    "COUNT(*) AS total "
    "FROM review_candidate"
)
print("修正后:", cur.fetchone())

conn.close()
