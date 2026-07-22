#!/usr/bin/env bash
# Ruijie CDP — 局域网部署脚本（仅前端 + 后端，数据库用远程云 MySQL）
#
# 用法:
#   ./deploy.sh            # 构建并后台启动（连云 MySQL）
#   ./deploy.sh rebuild    # 强制重新构建
#   ./deploy.sh down       # 停止并移除容器
#   ./deploy.sh logs       # 实时日志
#   ./deploy.sh ps         # 容器状态
#
# 说明:
#   - 本套「不含」MySQL，数据库为远程云 MySQL（由 backend/.env.development 配置）。
#   - backend 容器通过 APP_ENV=development + env_file: ../../backend/.env.development
#     加载云库连接配置（DB_HOST=192.168.159.22 / DB_PORT=33307 / ...）。
#   - 使用 host 网络模式（network_mode: host），nginx 直接监听宿主机 28080，
#     后端监听 8000，可供局域网内其他机器访问 http://<本机局域网IP>:28080。
#   - 构建上下文为项目根目录（../../），backend/、frontend/ 源码可被正确打包。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- 依赖检查 ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] 未检测到 docker，请先安装 Docker（或 docker-ce）。" >&2
  exit 1
fi
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "[ERROR] 未检测到 docker compose，请升级 Docker 到含 compose 插件的版本。" >&2
  exit 1
fi

# ---------- 镜像加速（podman 默认 registry 不可达时回退 docker.io） ----------
if command -v podman >/dev/null 2>&1; then
  if [ -z "${CONTAINERS_REGISTRIES^^}" ]; then
    mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/containers"
    if [ ! -f "${XDG_CONFIG_HOME:-$HOME/.config}/containers/registries.conf" ]; then
      cat > "${XDG_CONFIG_HOME:-$HOME/.config}/containers/registries.conf" <<'EOF'
unqualified-search-registries = ["docker.io"]
EOF
    fi
  fi
  # podman 3.x 存在 CNI 缺陷，host 网络模式可规避；本 compose 已统一使用 network_mode: host
  echo "[INFO] 检测到 podman，已使用 host 网络模式规避 CNI 问题。"
fi

# ---------- 开发/云库配置检查 ----------
# 局域网部署依赖云 MySQL，必须存在 backend/.env.development（含真实连接信息）。
DEV_ENV_FILE="../../backend/.env.development"
if [ ! -f "$DEV_ENV_FILE" ]; then
  echo "[ERROR] 未找到 $DEV_ENV_FILE（开发/云库配置）。" >&2
  echo "        请先创建 backend/.env.development（可复制 backend/.env.example 并填入云 MySQL 值），" >&2
  echo "        其中 DB_HOST=192.168.159.22、DB_PORT=33307、DB_NAME=app_cdp。" >&2
  exit 1
fi

# ---------- 动作 ----------
ACTION="${1:-up}"
case "$ACTION" in
  up)
    echo "==> 构建并启动服务（后台，连接远程云 MySQL）..."
    $DC up -d --build
    echo ""
    echo "部署完成！"
    echo "  前端页面： http://<本机局域网IP>:28080"
    echo "  后端接口： http://<本机局域网IP>:28080/api/"
    echo "  健康检查： http://<本机局域网IP>:28080/api/health"
    echo ""
    echo "查看日志： ./deploy.sh logs"
    ;;
  rebuild)
    echo "==> 强制重新构建并启动..."
    $DC up -d --build --force-recreate
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
    echo "用法: $0 {up|rebuild|down|logs|ps}"
    exit 1
    ;;
esac
