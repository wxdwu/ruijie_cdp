---
name: deploy
description: >-
  This skill should be used when deploying the Ruijie CDP project to a
  production (Docker) environment or starting the development (local) environment.
  It covers the full deployment workflow via deploy/deploy.sh, Docker Compose
  service composition, health checks, environment configuration, and common
  failure troubleshooting. Activate it when the user mentions deploying, going
  live, publishing, rebuilding, restarting services, or running the project in
  production/development mode.
---

# Ruijie CDP 部署技能

本技能封装了 Ruijie CDP 项目的标准部署流程，供 AI 在需要部署/上线项目时按规范执行。

## 触发条件

当用户提及以下意图时，自动激活本 Skill：
- "部署"、"上线"、"发布"、"deploy"
- "启动生产环境"、"docker 部署"
- "重建"、"重启服务"、"rebuild"

## 架构概述

本项目一套源码支持开发/生产双模式，业务代码一致，差异仅体现在环境配置文件：

| 模式 | 后端 | 前端 | 数据库 |
|------|------|------|--------|
| **开发** | 本地进程 `uvicorn --reload` | `npm run dev` | 云 MySQL (192.168.159.22:33307) |
| **生产** | Docker 容器 | Docker Nginx | 本机 Docker MySQL |

## 生产模式部署（Docker）

### 前置检查

部署前必须确认以下条件，条件不满足则终止并告知用户：

1. **Docker 已安装**：`docker --version` 或 `podman --version`
2. **Docker Compose 可用**：`docker compose version` 或 `docker-compose --version`
3. **端口未被占用**：3306（MySQL）、8000（Backend）、28080（Nginx）
4. **生产环境配置文件存在**：`backend/.env.production`（若缺失，deploy.sh 会自动从 `.env.example` 生成）
5. **SQL 初始化脚本完整**：
   - `deploy/sql_init/00_init_user.sql`（创建 app_cdp 账号）
   - `deploy/sql_init/01_init_table_struc.sql`（建库+表结构）
   - `deploy/sql_init/02_init_table_data.sql`（初始化数据）

### 部署命令（在 deploy/ 目录下执行）

```bash
cd /home/ubuntu/workspace/ruijie-cdp/deploy
sudo bash deploy.sh up       # 构建并启动所有服务（MySQL + Backend + Nginx）
sudo bash deploy.sh rebuild  # 强制重新构建（代码更新后）
sudo bash deploy.sh down     # 停止并移除所有容器
sudo bash deploy.sh logs     # 实时查看所有容器日志
sudo bash deploy.sh ps       # 查看容器运行状态
sudo bash deploy.sh reinit   # 清空 MySQL 数据卷（下次启动重新初始化数据库）
```

### 部署流程（deploy.sh up 内部步骤）

1. **依赖检查**：验证 docker、docker compose 可用
2. **Podman 镜像加速**：若检测到 podman，自动配置 Docker Hub 镜像源
3. **清理旧网络**：移除历史遗留的 CNI 网络
4. **SQL 初始化脚本检查**：验证 3 个 SQL 文件存在
5. **生产环境配置检查**：若 `backend/.env.production` 不存在，从 `.env.example` 复
   制并告警
6. **构建并启动**：`docker compose up -d --build`
7. **等待 MySQL 就绪**：轮询 `mysqladmin ping`，最长等待 120×10s=20 分钟
8. **输出访问地址**：前端 `http://<IP>:28080`，后端 `http://<IP>:28080/api/`

### 服务组成（docker-compose.yml）

| 服务 | 镜像/构建 | 端口 | 依赖 | 说明 |
|------|----------|------|------|------|
| mysql | `mysql:8.4` | 3306 | 无 | 首次启动自动执行 initdb 脚本 |
| backend | `deploy/backend.Dockerfile` | 8000 | mysql healthy | Python FastAPI + Uvicorn |
| nginx | `deploy/frontend.Dockerfile` | 28080 | backend healthy | 前端静态资源 + 反向代理 /api→8000 |

所有服务使用 `network_mode: host`（共享宿主机网络栈）。

### 容器健康检查

- **MySQL**：`mysqladmin ping` + 确认 `app_cdp` 库已创建
- **Backend**：HTTP GET `http://127.0.0.1:8000/api/health`
- **Nginx**：HTTP GET `http://127.0.0.1:28080/api/health`

### 关键文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| 部署脚本 | `deploy/deploy.sh` | 一键部署入口 |
| Docker Compose | `deploy/docker-compose.yml` | 服务编排定义 |
| 后端 Dockerfile | `deploy/backend.Dockerfile` | Python 3.13 镜像 |
| 前端 Dockerfile | `deploy/frontend.Dockerfile` | Node 构建 + Nginx 运行 |
| Nginx 配置 | `deploy/nginx/default.conf` | 反向代理规则 |
| SQL 初始化 | `deploy/sql_init/` | MySQL 首次启动脚本 |
| 后端生产配置 | `backend/.env.production` | DB/LLM/ES 等配置 |
| 后端配置模板 | `backend/.env.example` | 配置模板（占位符） |

### 常见问题排查

#### 部署失败 — MySQL 未就绪

```
[ERROR] MySQL 在预期时间内未就绪
```

原因：SQL 初始化脚本过大，导入耗时超时；或脚本有语法错误。
解决方案：
1. 执行 `./deploy.sh logs` 查看 MySQL 容器日志
2. 尝试 `./deploy.sh reinit` 清空数据卷后重试

#### 端口冲突

若 3306/8000/28080 被占用，需先释放端口或修改 docker-compose.yml 中的端口映射。

#### 配置文件缺失

若 `backend/.env.production` 缺失，deploy.sh 会从 `.env.example` 自动生成，
但需要用户确认其中的 `DB_*`、`LLM_*` 等配置值是否正确。

#### SQLBot 数据源配置

SQLBot 为独立 Docker 容器（端口 8020/8021），不在本 compose 中管理。
生产模式下 SQLBot 连接 MySQL 时，主机地址必须填 `172.18.0.1`（Docker 桥接网关），
**不能填 127.0.0.1**（容器内 127.0.0.1 不可达宿主机）。

若网关 IP 变化，用以下命令确认：
```bash
sudo docker inspect sqlbot --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'
```

## 开发模式（非 Docker，本地进程）

```bash
# 后端
cd /home/ubuntu/workspace/ruijie-cdp/backend
APP_ENV=development uvicorn app.main:app --reload --port 8000

# 前端
cd /home/ubuntu/workspace/ruijie-cdp/frontend
npm run dev
```

- 后端访问：http://127.0.0.1:8000
- 前端访问：http://127.0.0.1:8001

## LLM 执行部署的标准流程

当用户要求部署项目时，LLM 应按以下步骤执行：

1. **读取本 Skill 文件**，了解完整的部署流程
2. **检查前置条件**：确认 Docker、端口、配置文件
3. **执行部署**：
   ```bash
   cd /home/ubuntu/workspace/ruijie-cdp/deploy && sudo bash deploy.sh up
   ```
   （若用户未明确要求 sudo，需先询问用户是否允许使用 sudo）
4. **验证结果**：
   ```bash
   curl -s http://127.0.0.1:28080/api/health
   ```
   期望返回 200 状态码。
5. **输出访问地址**：告知用户前端和后端的访问 URL

### 其他常用操作

```bash
# 查看运行状态
cd /home/ubuntu/workspace/ruijie-cdp/deploy && sudo bash deploy.sh ps

# 查看实时日志
cd /home/ubuntu/workspace/ruijie-cdp/deploy && sudo bash deploy.sh logs

# 代码更新后重建
cd /home/ubuntu/workspace/ruijie-cdp/deploy && sudo bash deploy.sh rebuild

# 完全停止
cd /home/ubuntu/workspace/ruijie-cdp/deploy && sudo bash deploy.sh down
```
