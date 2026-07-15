#!/usr/bin/env bash
#
# Ruijie CDP 一键部署脚本
# --------------------------------------------------
# 基于 deploy/ 目录下的 docker-compose 构建并启动「后端 + 前端(Nginx)」。
#
# 用法：
#   ./deploy.sh            # 构建并后台启动服务
#   ./deploy.sh rebuild    # 强制重新构建（代码更新后使用）
#   ./deploy.sh down       # 停止并移除容器
#   ./deploy.sh logs       # 实时查看日志
#   ./deploy.sh ps         # 查看容器状态
#
# 说明：
#   - 构建上下文为项目根目录（..），因此 backend/、frontend/ 源码可被正确打包。
#   - 后端配置通过 ../backend/.env 注入（数据库 / LLM / ES 等）。
#   - 前端在 nginx 镜像内完成构建，最终由 Nginx 统一对外提供 28080 端口。
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

# ---------- 后端环境变量检查 ----------
# 后端全部数据库 / LLM 配置均来自 ../backend/.env（相对路径，通用适配）
ENV_FILE="../backend/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "[ERROR] 未找到 $ENV_FILE，后端无法读取数据库 / LLM 等配置。" >&2
  echo "        请参考 backend/.env 示例创建该文件后再执行部署。" >&2
  exit 1
fi
if ! grep -q '^DB_PASSWORD=' "$ENV_FILE"; then
  echo "[ERROR] $ENV_FILE 中缺少 DB_PASSWORD，请补充数据库密码配置。" >&2
  exit 1
fi

ACTION="${1:-up}"

case "$ACTION" in
  up)
    echo "==> 构建并启动服务（后台）..."
    $DC up -d --build
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
