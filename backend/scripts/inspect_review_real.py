"""只读探查真实库 review_candidate：找「need_review + 两侧都有联系人 + 共享联系人>0」的真实候选对。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.engine import get_session  # noqa: E402
from sqlalchemy import text  # noqa: E402


def main() -> None:
    s = get_session()
    try:
        # 先确认三张相关表的列结构，避免读错字段
        for tbl in ("dws_customer_360", "dws_contact_360", "dws_contact_mapping"):
            cols = s.execute(text(f"SHOW COLUMNS FROM {tbl}")).mappings().all()
            print(f"{tbl} 列: {[c['Field'] for c in cols]}")

        print("\n--- 真实候选：need_review + 两侧都有真实联系人（按两侧联系人数之和降序）---")
        rows = s.execute(text("""
            SELECT rc.id,
                   rc.candidate_a_name,
                   rc.candidate_b_name,
                   a.contact_count AS a_cc,
                   b.contact_count AS b_cc,
                   CAST(JSON_EXTRACT(rc.evidence, '$.shared_contacts_count') AS UNSIGNED) AS shared
            FROM review_candidate rc
            JOIN dws_customer_360 a ON a.id = rc.candidate_a_id
            JOIN dws_customer_360 b ON b.id = rc.candidate_b_id
            WHERE rc.status = 'need_review'
              AND a.contact_count > 0 AND b.contact_count > 0
            ORDER BY (a.contact_count + b.contact_count) DESC
            LIMIT 20
        """)).mappings().all()
        for r in rows:
            print(f"  id={r['id']} | {r['candidate_a_name']} (联系人{r['a_cc']}) "
                  f"<-> {r['candidate_b_name']} (联系人{r['b_cc']}) | 共享联系人={r['shared']}")
        if not rows:
            print("  无符合条件的候选")
    finally:
        s.close()


if __name__ == "__main__":
    main()
