# Ruijie CDP — 开发 / 生产双模式说明

本项目一套源码同时支持 **开发（development）** 与 **生产（production）** 两种模式，
**业务代码逻辑完全一致**，差异仅通过环境配置文件区分（主要是数据库与 SQLBot 数据源）。

## 模式切换机制

| 层 | 机制 | 开发（development） | 生产（production） |
|----|------|--------------------|--------------------|
| 后端 | 环境变量 `APP_ENV` 选择 `backend/.env.{APP_ENV}` | `APP_ENV=development` → `backend/.env.development`（连**云 MySQL**，默认） | `APP_ENV=production` → `backend/.env.production`（连**本机 docker MySQL**，需显式指定） |
| 前端 | Vite 内置 mode 加载 `frontend/.env.{mode}` | `npm run dev`（mode=development，默认） | `npm run build`（mode=production） |
| 部署 | `deploy/deploy.sh` | 本地进程，不用 docker | `sudo bash deploy.sh up`，docker 全套 |

后端配置优先级：**进程环境变量 > `.env.{APP_ENV}` 文件 > `config.py` 默认值**。
默认 `APP_ENV=development`（本地开发最频繁）；生产环境由 `deploy/docker-compose.yml` 显式设置 `APP_ENV=production`，故 docker 部署仍走生产配置。

## 一、开发模式（本地进程，连云 MySQL）

首次准备（如无 env 文件，从模板复制后填入真实值）：

```bash
cd backend
cp .env.example .env.development   # 然后把 DB_* 改为云 MySQL 值
```

启动后端（热更新）：

```bash
cd backend
APP_ENV=development uvicorn app.main:app --reload --port 8000
```

启动前端（Vite dev server，自动 mode=development，代理 /api → 127.0.0.1:8000）：

```bash
cd frontend
npm run dev
```

- 后端：http://127.0.0.1:8000
- 前端：http://127.0.0.1:8001

## 二、生产模式（docker 部署，连本机 docker MySQL）

```bash
cd deploy
sudo bash deploy.sh up        # 构建并启动 mysql + backend + nginx
sudo bash deploy.sh logs      # 实时日志
sudo bash deploy.sh ps        # 容器状态
sudo bash deploy.sh down      # 停止
sudo bash deploy.sh reinit    # 清空 MySQL 数据卷后重新初始化
```

- `deploy.sh` 会自动检查 `backend/.env.production`，缺失时用 `.env.example` 生成并告警。
- backend 容器通过 `APP_ENV=production` + `env_file: backend/.env.production` 加载生产配置。
- 访问：前端 `http://<服务器IP>:28080`，后端接口 `http://<服务器IP>:28080/api/`。

## 三、环境配置文件一览

| 文件 | 是否入库 | 说明 |
|------|---------|------|
| `backend/.env.example` | ✅ 提交 | 模板（占位符，无真实密钥） |
| `backend/.env.development` | ❌ gitignore | 开发配置（云 MySQL，真实密钥） |
| `backend/.env.production` | ❌ gitignore | 生产配置（本机 docker MySQL） |
| `frontend/.env.development` | ❌ gitignore | 前端开发配置（`VITE_API_BASE_URL`） |
| `frontend/.env.production` | ❌ gitignore | 前端生产配置（`VITE_API_BASE_URL`） |

## 四、SQLBot 数据源配置清单（外部容器，需在其 Web UI 中配置）

SQLBot 是独立 docker 容器（端口 8020/8021），不属于本仓库代码；它与本项目的差异仅体现为
「新建数据源时连接哪个 MySQL」。按当前模式在 SQLBot 页面填写：

| 模式 | 主机名/IP | 端口 | 用户 | 密码 | 数据库 | 说明 |
|------|----------|------|------|------|--------|------|
| 开发（连云 MySQL） | `192.168.159.22` | `33307` | `root` | 云库密码 | `app_cdp` | 直接填云 MySQL 地址 |
| 生产（连本机 docker MySQL） | `172.18.0.1` | `3306` | `root` | `123456` | `app_cdp` | **不能填 127.0.0.1**：SQLBot 容器自身 127.0.0.1 不可达宿主机，须用 docker 桥接网关 `172.18.0.1` |

> 提示：`172.18.0.1` 为 docker 自动分配的网关 IP，若 SQLBot 网络重建后变化，可用
> `sudo docker inspect sqlbot --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'`
> 重新确认，或改用宿主机真实 IP（需放行 3306）。
