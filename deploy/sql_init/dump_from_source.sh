#!/usr/bin/env bash
#
# 从源库（经 SSH 反向隧道 127.0.0.1:33307）导出 app_cdp 的库结构与数据。
# 凭据取自 backend/.env（DB_HOST=127.0.0.1 / DB_PORT=33307 / root / app_cdp）。
#
# 产物（文件名与 docker-compose 中 mysql 的 initdb 挂载一致，字典序自动执行）：
#   01_init_table_struc.sql —— CREATE DATABASE + 全部表结构（含索引），不含数据
#   02_init_table_data.sql  —— 仅数据；非 ods 表全量，ods* 表仅前 10000 条
#                              （dws_interaction_detail* 前 10 万；bench_* 不导数据）
#
set -euo pipefail

CREDS="-uroot -pt2yccidfsbseang1 -h127.0.0.1 -P33307"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRUC="$SCRIPT_DIR/01_init_table_struc.sql"
DATA="$SCRIPT_DIR/02_init_table_data.sql"

echo "==> 连通性检查"
mysql $CREDS -e "SELECT 1;" >/dev/null || { echo "[ERROR] 无法连接源库，请确认隧道已建立（127.0.0.1:33307）" >&2; exit 1; }

echo "==> 导出表结构（含索引，不含数据）-> $STRUC"
mysqldump $CREDS --databases app_cdp --no-data --routines --triggers --default-character-set=utf8mb4 > "$STRUC"

echo "==> 导出数据 -> $DATA"
{
  echo "USE app_cdp;"
  echo "SET NAMES utf8mb4;"
  echo "SET FOREIGN_KEY_CHECKS=0;"
} > "$DATA"

TABLES=$(mysql $CREDS -N -e "SHOW TABLES;" app_cdp)
for t in $TABLES; do
  case "$t" in
    # 这两张表不迁移任何数据
    bench_interaction_detail|bench_linkflow_contacts)
      echo "  [跳过数据] $t"
      continue
      ;;
    # 这两张表仅保留前 10 万条
    dws_interaction_detail|dws_interaction_detail_backup)
      echo "  [限前100000条] $t"
      mysqldump $CREDS --no-create-info --default-character-set=utf8mb4 --where="1=1 LIMIT 100000" app_cdp "$t" >> "$DATA"
      ;;
    # ods* 表数据量大，仅前 1 万条
    ods*)
      echo "  [ods, 限前10000条] $t"
      mysqldump $CREDS --no-create-info --default-character-set=utf8mb4 --where="1=1 LIMIT 10000" app_cdp "$t" >> "$DATA"
      ;;
    # 其余表全量
    *)
      echo "  [全量] $t"
      mysqldump $CREDS --no-create-info --default-character-set=utf8mb4 app_cdp "$t" >> "$DATA"
      ;;
  esac
done
echo "SET FOREIGN_KEY_CHECKS=1;" >> "$DATA"

echo "==> 完成"
echo "    结构: $STRUC"
echo "    数据: $DATA"
