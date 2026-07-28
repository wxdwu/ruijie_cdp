"""只读诊断：company_merge_map 中与 三花/三环 相关的真实映射，以及 resolve_customer 的实际返回。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.engine import get_session  # noqa: E402
from app.services.company_dedup import company_merge  # noqa: E402
from sqlalchemy import text  # noqa: E402


def main() -> None:
    s = get_session()
    try:
        rows = s.execute(text(
            "SELECT id, alias_name, canonical_name, canonical_id, review_id, merge_source "
            "FROM company_merge_map "
            "WHERE alias_name LIKE '%三花%' OR canonical_name LIKE '%三花%' "
            "   OR alias_name LIKE '%三环%' OR canonical_name LIKE '%三环%'"
        )).mappings().all()
        print("company_merge_map 含 三花/三环 的记录:")
        for r in rows:
            print(" ", dict(r))
        print("共", len(rows), "条")

        cid_a = s.execute(
            text("SELECT id FROM dws_customer_360 WHERE customer_name = '三花控股'")
        ).scalar()
        print("三花控股 id =", cid_a)
        res = company_merge.resolve_customer(s, cid_a)
        print("resolve_customer(三花控股) =", res)
    finally:
        s.close()


if __name__ == "__main__":
    main()
