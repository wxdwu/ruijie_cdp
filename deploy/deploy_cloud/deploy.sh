#!/usr/bin/env bash
#
# Ruijie CDP 一键部署脚本
# --------------------------------------------------
# 基于 deploy/deploy_cloud/ 目录下的 docker-compose 构建并启动「后端 + 前端(Nginx) + 本机 MySQL」。
#
# 用法：
#   ./deploy.sh            # 构建并后台启动服务（含等待 MySQL 初始化完成）
#   ./deploy.sh rebuild    # 强制重新构建（代码更新后使用）
#   ./deploy.sh reinit     # 清空 MySQL 数据卷，下次启动重新初始化数据库
#   ./deploy.sh down       # 停止并移除容器
#   ./deploy.sh logs       # 实时查看日志
#   ./deploy.sh ps         # 查看容器状态
#
# 说明：
#   - 构建上下文为项目根目录（..），因此 backend/、frontend/ 源码可被正确打包。
#   - 数据库为本机 docker MySQL（compose 中的 mysql 服务），首次启动自动执行
#     sql_init/ 下的建表与数据脚本。
#   - 本脚本为「生产模式」部署：docker-compose.yml 已显式注入 APP_ENV=production
#     （覆盖 config.py 默认的 development），并通过 env_file: ../../backend/.env.production
#     加载生产配置（连本机 docker MySQL）。
#     开发模式（连云 MySQL）请在本地运行：
#       APP_ENV=development uvicorn app.main:app --reload --port 8000  （后端）
#       npm run dev                                                     （前端）
#   - 前端在 nginx 镜像内完成构建，最终由 Nginx 统一对外提供 28080 端口。
#   - 构建上下文为项目根目录（../../），backend/、frontend/ 源码可被正确打包。
#
set -euo pipefail

# 切换到脚本所在目录（deploy）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- 依赖检查 ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] 未检测到 docker，请先安装 Docker：https://docs.docker.com/get-docker/" >&2
  exit 1
fi

# 兼容 docker compose v2 与 docker-compose v1
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "[ERROR] 未检测到 docker compose 插件或 docker-compose，请先安装。" >&2
  exit 1
fi

# ---------- 镜像加速（podman 环境） ----------
# 国内直连 Docker Hub 常超时，这里为 podman 自动配置 Docker Hub 镜像加速。
# 镜像站点可通过环境变量 PODMAN_MIRROR 覆盖，默认使用已验证可用的 docker.1ms.run。
if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  PODMAN_MIRROR="${PODMAN_MIRROR:-docker.1ms.run}"
  MIRROR_CONF="/etc/containers/registries.conf.d/docker-mirror.conf"
  if ! grep -q "$PODMAN_MIRROR" "$MIRROR_CONF" 2>/dev/null; then
    # 已是 root（如 sudo ./deploy.sh）则直接写，否则用 sudo
    if [ "$(id -u)" -eq 0 ]; then
      WRITE_CMD=(tee)
    else
      WRITE_CMD=(sudo tee)
    fi
    echo "[INFO] 检测到 podman 且未配置镜像加速，自动写入 Docker Hub 镜像源..."
    if "${WRITE_CMD[@]}" "$MIRROR_CONF" > /dev/null <<EOF
unqualified-search-registries = ["docker.io"]

[[registry]]
prefix = "docker.io"
location = "docker.io"

[[registry.mirror]]
location = "$PODMAN_MIRROR"

[[registry.mirror]]
location = "docker.m.daocloud.io"

[[registry.mirror]]
location = "dockerproxy.net"
EOF
    then
      echo "[INFO] 镜像加速已配置：$MIRROR_CONF"
    else
      echo "[WARN] 写入镜像加速配置失败（可能无 sudo 权限）。若拉取镜像超时，请手动配置 $MIRROR_CONF。" >&2
    fi
  else
    echo "[INFO] 已检测到 Docker Hub 镜像加速配置，跳过。"
  fi
fi

# ---------- 网络模式说明 ----------
# 本部署使用 network_mode: host（容器共享宿主机网络栈），
# 不创建任何 CNI/bridge 自定义网络，因此无需 netavark，也不会触发
# podman 3.x 的 "CNI network not found" 问题。
# 仅做一层兜底：若历史遗留的本项目 CNI 网络存在则清理，避免干扰。
if command -v podman >/dev/null 2>&1; then
  podman network rm deploy_ruijie_cdp >/dev/null 2>&1 || true
fi

# ---------- 数据库初始化脚本检查 ----------
# 本机 docker MySQL 首次启动（数据卷为空时）会按字典序自动执行 sql_init/ 下脚本：
#   00_init_user.sql        创建 app_cdp 账号并授予全库权限（随仓库提供）
#   01_init_table_struc.sql 建库 + 表结构（含索引）
#   02_init_table_data.sql  导入初始化数据
# 01/02 由 sql_init/dump_from_source.sh 从源库导出（不纳入版本库，需本地存在）。
for f in "./sql_init/00_init_user.sql" "./sql_init/01_init_table_struc.sql" "./sql_init/02_init_table_data.sql"; do
  if [ ! -f "$f" ]; then
    echo "[ERROR] 未找到 $f，MySQL 无法完成初始化。" >&2
    if [[ "$f" == *00_init_user.sql ]]; then
      echo "        该文件用于创建 app_cdp 账号，应随仓库提供。" >&2
    else
      echo "        请先运行 sql_init/dump_from_source.sh 从源库导出建表与数据脚本。" >&2
    fi
    exit 1
  fi
done

# ---------- 生产环境配置文件检查 ----------
# docker-compose.yml 的 backend 服务通过 env_file 加载 ../../backend/.env.production，
# 缺失会导致 compose 解析失败，故此处兜底：不存在则由 .env.example 生成并告警。
PROD_ENV_FILE="../../backend/.env.production"
ENV_TEMPLATE="../../backend/.env.example"
if [ ! -f "$PROD_ENV_FILE" ]; then
  echo "[WARN] 未找到 $PROD_ENV_FILE（生产环境后端配置）。" >&2
  if [ -f "$ENV_TEMPLATE" ]; then
    cp "$ENV_TEMPLATE" "$PROD_ENV_FILE"
    echo "[INFO] 已由模板生成 $PROD_ENV_FILE，请确认其中 DB_* / LLM_* 等为生产环境正确值。" >&2
  else
    echo "[ERROR] 模板 $ENV_TEMPLATE 也不存在，无法生成生产配置。请手动创建 $PROD_ENV_FILE。" >&2
    exit 1
  fi
fi

ACTION="${1:-up}"

# 等待 MySQL 完成初始化（initdb 执行完、3306 可连、app_cdp 库已建）
wait_mysql_ready() {
  local max="${1:-120}"
  for i in $(seq 1 "$max"); do
    if $DC exec -T mysql mysqladmin ping -h127.0.0.1 -P3306 -uroot -p123456 --silent >/dev/null 2>&1; then
      return 0
    fi
    echo "    ... MySQL 初始化中（${i}/${max}），大体积数据导入可能耗时数分钟"
    sleep 10
  done
  return 1
}

case "$ACTION" in
  up)
    echo "==> 构建并启动服务（后台）..."
    $DC up -d --build
    echo ""
    echo "==> 等待 MySQL 初始化完成（建库/建表/导数据）..."
    if wait_mysql_ready 120; then
      echo "[OK] MySQL 已就绪，初始化完成。"
    else
      echo "[ERROR] MySQL 在预期时间内未就绪，请查看日志排查： ./deploy.sh logs" >&2
      echo "        常见原因：01/02 SQL 导入失败，或数据卷为旧残留。" >&2
      echo "        可尝试先执行 ./deploy.sh reinit 清空数据卷，再重新 ./deploy.sh。" >&2
      exit 1
    fi
    echo ""
    echo "部署完成！"
    echo "  前端页面： http://<服务器IP>:28080"
    echo "  后端接口： http://<服务器IP>:28080/api/"
    echo "  健康检查： http://<服务器IP>:28080/api/health"
    echo ""
    echo "查看日志： ./deploy.sh logs"
    ;;
  rebuild)
    echo "==> 强制重新构建并启动..."
    $DC up -d --build --force-recreate
    ;;
  reinit)
    # 清空 MySQL 数据卷，下次 ./deploy.sh 将重新执行 initdb 脚本（00/01/02）完成初始化。
    echo "==> 停止并移除 MySQL 容器，清空数据卷..."
    $DC stop mysql >/dev/null 2>&1 || true
    $DC rm -f mysql >/dev/null 2>&1 || true
    VOL=$(docker volume ls -q 2>/dev/null | grep -i mysql_data | head -1 || true)
    if [ -n "$VOL" ]; then
      docker volume rm "$VOL" >/dev/null 2>&1 && echo "[INFO] 已删除数据卷：$VOL"
    else
      echo "[WARN] 未找到 MySQL 数据卷，可能尚未创建。"
    fi
    echo "完成。请重新执行 ./deploy.sh 进行初始化。"
    ;;
  down)
    echo "==> 停止并移除容器..."
    $DC down
    ;;
  logs)
    $DC logs -f
    ;;
  ps)
    $DC ps
    ;;
  *)
    echo "用法: $0 {up|rebuild|reinit|down|logs|ps}"
    exit 1
    ;;
esac
