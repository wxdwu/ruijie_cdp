# Ruijie CDP — 局域网部署（仅前端 + 后端，使用云 MySQL）

> 本目录 `deploy/deploy_local/` 为**局域网内部署**方案：只需部署**前端 + 后端**两个服务，
> 数据库直接连接**远程云 MySQL**（`192.168.159.22:33307 / app_cdp`），即 `backend/.env.development` 中的配置。
> 适合「内网机器不想再起一套 MySQL、统一用云端数仓」的场景。
> 公网独立部署（本机 MySQL + 前后端）请见同级 `../deploy_cloud/` 目录。

## 与公网部署（deploy_cloud）的区别

| 项 | deploy_local（本目录） | deploy_cloud（公网） |
|---|---|---|
| MySQL | 无，连接远程云 MySQL | 本机 docker MySQL 服务 |
| sql_init | 无（云库已就绪） | 有，首次启动自动建表/灌数据 |
| backend 配置 | `APP_ENV=development` + `backend/.env.development`（云库） | `APP_ENV=production` + `backend/.env.production`（本机库） |
| 服务数 | 2（backend + nginx） | 3（mysql + backend + nginx） |
| 适用 | 局域网内访问云数仓 | 不同公网 IP 独立部署全套 |

## 部署步骤

```bash
cd deploy/deploy_local

# 1) 确认云库配置存在（含真实连接信息，已被 .gitignore 忽略）
#    若 backend/.env.development 不存在，先复制 backend/.env.example 并填入云 MySQL 值：
#      DB_HOST=192.168.159.22
#      DB_PORT=33307
#      DB_NAME=app_cdp
#      DB_USER=root
#      DB_PASSWORD=****

# 2) 一键构建并启动
sudo bash deploy.sh up        # 构建并后台启动 backend + nginx
sudo bash deploy.sh logs      # 实时日志
sudo bash deploy.sh ps        # 容器状态
sudo bash deploy.sh down      # 停止
sudo bash deploy.sh rebuild   # 强制重新构建
```

## 访问方式

使用 `network_mode: host`，nginx 直接监听宿主机 `28080`，后端监听 `8000`：

- 前端页面： `http://<本机局域网IP>:28080`
- 后端接口： `http://<本机局域网IP>:28080/api/`
- 健康检查： `http://<本机局域网IP>:28080/api/health`

> 局域网内其他机器用宿主机局域网 IP 访问即可；确保宿主机 8000/28080 端口未被占用、
> 且能访问 `192.168.159.22:33307` 云 MySQL。

## 配置要点

- 构建上下文为**项目根目录**（`../../`），`docker-compose.yml` 中
  `context: ../../` + `dockerfile: deploy/deploy_local/xxx.Dockerfile`，
  因此 `backend/`、`frontend/` 源码可被正确打包。
- nginx 配置 `deploy/deploy_local/nginx/default.conf`：将 `/api/` 反代到 `http://127.0.0.1:8000`
  （host 网络下走 localhost，不依赖 docker 服务名 DNS）。
- `deploy.sh` 启动前会检查 `../../backend/.env.development` 是否存在，缺失即报错退出。

## SQLBot（外部 Excel 工具）

SQLBot 为独立 Excel 工具，连接的是 MySQL。局域网场景下它应连接**云 MySQL**
（`192.168.159.22:33307`，账号/库名同上），与开发模式一致；详见 `../deploy_cloud/README.md` 的 SQLBot 配置说明。
