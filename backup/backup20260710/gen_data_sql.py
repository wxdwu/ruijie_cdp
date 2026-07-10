"""
生成 app_cdp_data.sql：将现有库 app_cdp 中每个表的随机 1000 条数据写入该 SQL 文件。
规则：
  - 数据量 > 1000：随机抽取 1000 条；
  - 数据量 <= 1000：原封不动写入全量。
采样策略：
  - 有自增整数主键(id)的表：基于主键范围随机取 id(IN 查询，走索引，对千万级大表也很安全)；
  - 无自增主键的表：回退到 ORDER BY RAND() LIMIT 1000（仅少量中小表会走到此分支）。
用法：python gen_data_sql.py
"""
import random
from decimal import Decimal
from datetime import date, datetime, timedelta

import pymysql

DB = dict(
    host="192.168.159.22", port=33307, user="app_cdp",
    password="123456", database="app_cdp", charset="utf8mb4",
)
OUT = "app_cdp_data.sql"
N = 1000            # 每个表随机抽取的目标条数
CHUNK = 500         # 每个 INSERT 语句写入的行数，避免单条过大


def fmt(v):
    """将 Python 值格式化为 SQL 字面量。"""
    if v is None:
        return "NULL"
    if isinstance(v, (bytes, bytearray)):
        return "0x" + v.hex()
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, (datetime, date, timedelta)):
        return "'" + str(v) + "'"
    s = str(v)
    s = (
        s.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return "'" + s + "'"


def get_tables(cur):
    cur.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA='app_cdp' AND TABLE_TYPE='BASE TABLE' "
        "ORDER BY TABLE_NAME"
    )
    return [r[0] for r in cur.fetchall()]


def get_insertable_columns(cur, table):
    """返回可插入的列名列表（排除生成列），以及自增整数主键列名（若有）。"""
    cur.execute(
        "SELECT COLUMN_NAME, EXTRA, DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA='app_cdp' AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
        (table,),
    )
    cols, ai = [], None
    for name, extra, dtype in cur.fetchall():
        if "GENERATED" in extra.upper():   # 跳过生成列，不可手动插入
            continue
        cols.append(name)
        if "auto_increment" in extra and dtype in ("int", "bigint", "mediumint", "smallint"):
            ai = name
    return cols, ai


def fetch_rows(cur, table, cols, ai, count):
    colsql = ", ".join(f"`{c}`" for c in cols)
    if count <= N:
        # 全量写入
        cur.execute(f"SELECT {colsql} FROM `{table}`")
        return list(cur.fetchall()), count
    if ai:
        # 基于主键范围随机采样，避免大表全排序
        cur.execute(f"SELECT MIN(`{ai}`), MAX(`{ai}`) FROM `{table}`")
        mn, mx = cur.fetchone()
        if mn is None or mx is None:
            cur.execute(f"SELECT {colsql} FROM `{table}`")
            return list(cur.fetchall()), count
        collected = {}
        ai_idx = cols.index(ai)
        attempts = 0
        while len(collected) < N and attempts < 40:
            k = N + 500
            cand = [random.randint(mn, mx) for _ in range(k)]
            placeholders = ",".join(str(c) for c in cand)
            cur.execute(
                f"SELECT {colsql} FROM `{table}` WHERE `{ai}` IN ({placeholders})"
            )
            for row in cur.fetchall():
                rid = row[ai_idx]
                if rid not in collected:
                    collected[rid] = row
                    if len(collected) >= N:
                        break
            attempts += 1
        return list(collected.values()), count
    # 回退：ORDER BY RAND()（仅少量无自增主键的中小表）
    cur.execute(f"SELECT {colsql} FROM `{table}` ORDER BY RAND() LIMIT {N}")
    return list(cur.fetchall()), count


def main():
    conn = pymysql.connect(**DB, connect_timeout=15)
    cur = conn.cursor()
    tables = get_tables(cur)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("-- ─────────────────────────────────────────────────────────────\n")
        f.write("-- app_cdp 数据抽样导出 (每表随机 1000 条 / 不足则全量)\n")
        f.write("-- 由 gen_data_sql.py 生成，配合 app_cdp_struc.sql 使用\n")
        f.write("-- ─────────────────────────────────────────────────────────────\n")
        f.write("SET NAMES utf8mb4;\n")
        f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")

        for table in tables:
            cols, ai = get_insertable_columns(cur, table)
            colsql = ", ".join(f"`{c}`" for c in cols)
            cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            count = cur.fetchone()[0]
            rows, _ = fetch_rows(cur, table, cols, ai, count)
            if not rows:
                f.write(f"-- 表 `{table}`: 0 行 (源表为空或采样为空)\n\n")
                print(f"[skip ] {table}: 0 行")
                continue
            method = "全量" if count <= N else ("主键采样" if ai else "RAND()")
            written = len(rows)
            # 分块写入
            for i in range(0, written, CHUNK):
                chunk = rows[i : i + CHUNK]
                f.write(f"INSERT INTO `{table}` ({colsql}) VALUES\n")
                vals = []
                for row in chunk:
                    vals.append("(" + ",".join(fmt(v) for v in row) + ")")
                f.write(",\n".join(vals))
                f.write(";\n")
            f.write("\n")
            print(f"[ ok  ] {table}: 源={count} 写入={written} 方式={method}")

    conn.close()
    print(f"\n完成，输出文件: {OUT}")


if __name__ == "__main__":
    main()
