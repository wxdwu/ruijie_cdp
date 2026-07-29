"""真实库端到端验证（纯净版）：审核队列里的真实候选 -> 审核通过 -> 客户管理合并。

修复上一次污染：此前选的 id=37（三花控股）已被历史 auto_merge 并入三环集团，合并簇不纯净。
本脚本：
1) 回退上一次误写入的 id=37 映射（仅删 review_id=37 那一行）+ 状态改回 need_review；
2) 筛选「need_review + 两侧都有真实联系人 + 两侧都未参与过任何合并」的纯净候选；
3) 对第一条纯净候选走真实审核链路 approve_review，验证：
   - review_candidate.status -> merged（手动合并）
   - company_merge_map 写入（含 canonical_id）
   - 客户列表折叠（别名公司不再单独出现）
   - 点开标准名详情，联系人 = 两侧并集（重叠去重 + 独有补充）
   - 合并簇成员恰好 = {A, B}（纯净，未被历史映射污染）

副作用（可逆）：写入 company_merge_map 一行；review_candidate.status 变 merged（手动合并）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.engine import get_session  # noqa: E402
from app.services.company_dedup import company_merge, review_service  # noqa: E402
from sqlalchemy import text  # noqa: E402


def main() -> None:
    s = get_session()
    try:
        # 1) 回退上一次误写入的 id=37（仅删 review_id=37 那一行，不动历史映射）
        d = s.execute(
            text("DELETE FROM company_merge_map WHERE review_id = :rid"),
            {"rid": 37},
        )
        s.execute(
            text("UPDATE review_candidate SET status='need_review', "
                 "reviewed_by=NULL, reviewed_at=NULL WHERE id = :id"),
            {"id": 37},
        )
        s.commit()
        print(f"[回退] 删除误写映射行数={d.rowcount}，review_candidate(id=37) 已改回 need_review")

        # 2) 筛选纯净候选：两侧都有联系人，且两侧都未参与过任何合并。
        #    注意：review_candidate 与 company_merge_map 的 collation 不同
        #    (utf8mb4_0900_ai_ci vs utf8mb4_unicode_ci)，跨表 `=` 比较会报 1267。
        #    故改为先取候选，再在 Python 中排除已合并的公司名（同表内查询无冲突）。
        rows = s.execute(text("""
            SELECT rc.id,
                   rc.candidate_a_name,
                   rc.candidate_b_name,
                   a.contact_count AS a_cc,
                   b.contact_count AS b_cc
            FROM review_candidate rc
            JOIN dws_customer_360 a ON a.id = rc.candidate_a_id
            JOIN dws_customer_360 b ON b.id = rc.candidate_b_id
            WHERE rc.status = 'need_review'
              AND a.contact_count > 0 AND b.contact_count > 0
            ORDER BY (a.contact_count + b.contact_count) DESC
            LIMIT 200
        """)).mappings().all()
        merged_names = {
            r["alias_name"] for r in s.execute(
                text("SELECT alias_name FROM company_merge_map")).mappings().all()
        } | {
            r["canonical_name"] for r in s.execute(
                text("SELECT canonical_name FROM company_merge_map")).mappings().all()
        }
        clean = [
            r for r in rows
            if r["candidate_a_name"] not in merged_names
            and r["candidate_b_name"] not in merged_names
        ]
        print("[纯净候选列表]:")
        for r in clean[:10]:
            print(f"  id={r['id']} | {r['candidate_a_name']}(联系人{r['a_cc']}) "
                  f"<-> {r['candidate_b_name']}(联系人{r['b_cc']})")
        if not clean:
            print("  无纯净候选，终止")
            return
        item_id = clean[0]["id"]
        print(f"\n[选用] 纯净候选 id={item_id}")

        # 3) 端到端：对该纯净候选走审核链路
        item = s.execute(
            text("SELECT id, candidate_a_id, candidate_a_name, "
                 "candidate_b_id, candidate_b_name, status "
                 "FROM review_candidate WHERE id = :id"),
            {"id": item_id},
        ).mappings().fetchone()
        names = (item["candidate_a_name"], item["candidate_b_name"])
        # 收集两侧真实联系人（按公司名查 dws_contact_mapping，绕开 dws 表间 id 不一致）
        side_cons = {}
        side_info = {}
        for lbl, _cid, cname in (
            ("A", item["candidate_a_id"], item["candidate_a_name"]),
            ("B", item["candidate_b_id"], item["candidate_b_name"]),
        ):
            cons = s.execute(
                text("SELECT contact_name, mobile FROM dws_contact_mapping "
                     "WHERE customer_name = :n"),
                {"n": cname},
            ).mappings().all()
            info = s.execute(
                text("SELECT industry, region, owner_name, contact_count "
                     "FROM dws_customer_360 WHERE customer_name = :n"),
                {"n": cname},
            ).mappings().fetchone()
            side_cons[cname] = {(c["contact_name"], c["mobile"]) for c in cons}
            side_info[cname] = dict(info) if info else {}
            print(f"  [{lbl}] {cname} | 联系人{len(cons)}: "
                  f"{[(c['contact_name'], c['mobile']) for c in cons]} | 其他: {side_info[cname]}")

        before = [r["customer_name"] for r in s.execute(
            text("SELECT customer_name FROM dws_customer_360 "
                 "WHERE customer_name IN :names"),
            {"names": names},
        ).mappings().all()]
        print(f"[审核前] 客户列表(两公司): {before}")

        ret = review_service.approve_review(s, item_id, reviewed_by="审核员")
        print(f"[审核] approve_review 返回: {ret}")

        st = s.execute(
            text("SELECT status FROM review_candidate WHERE id = :id"),
            {"id": item_id},
        ).scalar()
        print(f"[审核] review_candidate.status = {st}")

        mm = s.execute(
            text("SELECT alias_name, canonical_name, canonical_id "
                 "FROM company_merge_map "
                 "WHERE canonical_name = :a OR alias_name = :b"),
            {"a": item["candidate_a_name"], "b": item["candidate_b_name"]},
        ).mappings().all()
        print(f"[合并映射(相关)] {[dict(r) for r in mm]}")
        all_mm = s.execute(
            text("SELECT id, alias_name, canonical_name, review_id, merge_source "
                 "FROM company_merge_map")
        ).mappings().all()
        print(f"[合并映射(全表)] {[dict(r) for r in all_mm]}")

        after = [r["customer_name"] for r in s.execute(
            text("SELECT customer_name FROM dws_customer_360 "
                 "WHERE customer_name IN :names "
                 "AND customer_name NOT IN (SELECT alias_name FROM company_merge_map)"),
            {"names": names},
        ).mappings().all()]
        print(f"[合并后] 客户列表(两公司): {after}")

        # 客户管理前端用的是 dws_customer_360 的真实 id（从列表点进来），
        # 而非 review_candidate 里可能已过期的 candidate_a_id
        real_a_id = s.execute(
            text("SELECT id FROM dws_customer_360 WHERE customer_name = :n"),
            {"n": item["candidate_a_name"]},
        ).scalar()
        _, _, mids, mnames = company_merge.resolve_customer(s, real_a_id)
        print(f"[合并后] 合并簇成员(按真实id解析): {mnames}")
        # 联系人合并：按合并簇成员名聚合 dws_contact_mapping（绕开 dws 表间 id 不一致）
        cons_all = s.execute(
            text("SELECT contact_name, mobile FROM dws_contact_mapping "
                 "WHERE customer_name IN :names"),
            {"names": tuple(mnames)},
        ).mappings().all()
        info_all = s.execute(
            text("SELECT customer_name, industry, region, owner_name "
                 "FROM dws_customer_360 WHERE customer_name IN :names"),
            {"names": tuple(mnames)},
        ).mappings().all()
        print(f"[合并后] 点开 {item['candidate_a_name']} 详情, 联系人({len(cons_all)}): "
              f"{[(c['contact_name'], c['mobile']) for c in cons_all]}")
        print(f"[合并后] 合并簇其他信息: {[dict(r) for r in info_all]}")

        cons_all_set = {(c["contact_name"], c["mobile"]) for c in cons_all}
        expected_cons = side_cons[item["candidate_a_name"]] | side_cons[item["candidate_b_name"]]
        ok = (
            ret["success"] and ret["status"] == "merged"
            and st == "merged"
            and mm
            and item["candidate_b_name"] not in after
            and item["candidate_a_name"] in after
            and set(mnames) == {item["candidate_a_name"], item["candidate_b_name"]}
            and cons_all_set == expected_cons
        )
        print("\n[RESULT]", "PASS" if ok else "FAIL")
    finally:
        s.close()


if __name__ == "__main__":
    main()
