# Ruijie CDP（CDP ABM 360）

瑞捷 CDP（Customer Data Platform / ABM 360）客户数据平台。一套源码同时支持
**开发模式**（本地进程，连云 MySQL）与 **生产模式**（Docker 部署，连本机 docker MySQL），
业务代码完全一致，差异仅通过环境配置（`APP_ENV`）区分。

> 部署与双模式详细说明见 [`deploy/README.md`](deploy/README.md)；AI 自动部署技能见
> [`skills/deploy/SKILL.md`](skills/deploy/SKILL.md)。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.13 / FastAPI / Uvicorn / SQLAlchemy / PyMySQL |
| 前端 | Vue 3 / Vite / Pinia / Vue Router / Tailwind CSS / ECharts |
| 存储 | MySQL 8.4（业务主库）+ ElasticSearch（检索/分析） |
| AI | LLM 对话（DeepSeek 等）+ Embedding + SQLBot 数据源 |
| 部署 | Docker / Docker Compose / Nginx |

---

## 目录结构

```
ruijie-cdp/
├── backend/                # 后端服务（FastAPI）
│   ├── app/
│   │   ├── main.py         # 应用入口（lifespan 调度、健康检查、ETL 触发）
│   │   ├── config/         # 配置（双模式 APP_ENV）
│   │   ├── database/       # 数据库连接与会话（SQLAlchemy engine/session）
│   │   ├── routers/        # API 路由层（10 个模块）
│   │   └── services/       # 业务逻辑层（ETL / ES / 去重 / LLM 等）
│   ├── requirements.txt
│   └── .env.{development|production}   # 环境配置（gitignore，不入库）
├── frontend/               # 前端应用（Vue 3 + Vite）
│   └── src/
│       ├── views/          # 页面级组件
│       ├── components/     # 通用组件（40+ .vue）
│       ├── api/            # 后端接口封装
│       ├── stores/         # Pinia 状态管理
│       ├── router/         # 路由
│       └── assets/styles/  # 静态资源与样式
├── deploy/                 # 生产部署（Docker）
│   ├── deploy.sh           # 一键部署脚本
│   ├── docker-compose.yml  # 服务编排（mysql/backend/nginx）
│   ├── backend.Dockerfile / frontend.Dockerfile
│   ├── nginx/              # Nginx 反向代理配置
│   ├── sql_init/           # MySQL 首次启动初始化脚本
│   └── SQLBot/             # SQLBot 相关配置
├── doc/                    # 设计/接口/数据流文档（Markdown）
├── scripts/                # 数据库迁移与同步脚本（SQL / Python / Shell）
├── file/                   # 数据导入脚本与原始 Excel 数据
├── skills/                 # AI 编程技能（deploy 自动部署技能）
├── backup/                 # 数据库/数据备份
└── README.md               # 本文件
```

---

## 分模块介绍

### 1. backend/ — 后端服务

基于 FastAPI 的 RESTful 后端，应用入口 [`main.py`](backend/app/main.py)：启动/关闭 ETL 调度器、
暴露 `GET /api/health` 健康检查、`POST /api/admin/etl/run` 手动触发 ETL（带并发锁）、
以及 `/demo` 原型演示页。

#### 1.1 `app/config/` — 配置
- `config.py`：按 `APP_ENV`（默认 `development`）加载 `backend/.env.{APP_ENV}`，
  配置优先级为「进程环境变量 > `.env.{APP_ENV}` 文件 > 默认值」。
  生产环境由 `deploy/docker-compose.yml` 显式注入 `APP_ENV=production`。

#### 1.2 `app/database/` — 数据访问
- `engine.py`：SQLAlchemy 引擎与连接池（含 `dispose_engine`）。
- `session.py`：数据库会话管理。

#### 1.3 `app/routers/` — API 路由层（10 个模块）
| 路由 | 职责 |
|------|------|
| `customer_list.py` | 客户列表查询/筛选 |
| `customer_detail.py` | 客户 360 详情 |
| `ai_chat.py` | AI 智能对话 |
| `campaign.py` | 营销活动与看板 |
| `review.py` | 审核队列 |
| `sync.py` | 数据同步接口 |
| `pool.py` | 客户池管理 |
| `es_sync.py` | ElasticSearch 同步接口 |
| `es_crud.py` | ElasticSearch 增删改查接口 |
| `monitor.py` | 表数据监控接口 |

#### 1.4 `app/services/` — 业务逻辑层
| 子模块 | 职责 |
|--------|------|
| `etl/` | ETL 调度（`etl_scheduler.py`）与同步（`etl_sync.py`），启动时自动运行 |
| `elasticSearch/` | ES 同步（`es_sync.py`）与 CRUD（`es_crud.py`） |
| `companyDedup/` | 公司名去重（`company_dedup.py`） |
| `monitor/` | 数据监控逻辑 |
| `llm_client.py` | LLM / Embedding 客户端封装 |
| `channel_classification.py` | 渠道分类 |
| `contact_recommend.py` | 联系人推荐 |
| `customer_service.py` | 客户服务逻辑 |
| `export_service.py` | 数据导出 |
| `interaction_service.py` | 互动行为处理 |
| `key_account_query.py` | 关键客户查询 |
| `opportunity_service.py` | 商机服务 |
| `region_filter.py` | 区域过滤 |
| `wasted/` | 已废弃代码（保留参考） |

---

### 2. frontend/ — 前端应用（Vue 3 + Vite）

基于 Vue 3 的单页应用，开发服务器（`npm run dev`）默认代理 `/api` → `127.0.0.1:8000`。

| 目录/文件 | 职责 |
|-----------|------|
| `views/` | 页面级组件：`CustomerList`（客户列表）、`CustomerDetail`（客户详情）、`CampaignBoard`（营销看板）、`ReviewQueue`（审核队列）、`AiChat` / `AiChatSqlBot`（AI 对话，含 SQLBot） |
| `components/` | 通用 UI 组件（40+ 个 `.vue`） |
| `api/index.js` | 后端接口统一封装（axios） |
| `stores/customer.js` | Pinia 客户状态管理 |
| `router/index.js` | 前端路由 |
| `assets/` `styles/` | 静态资源与全局样式 |

---

### 3. deploy/ — 生产部署

Docker 化部署，包含 `mysql` + `backend` + `nginx` 三个服务（均使用 `network_mode: host`）。

| 文件 | 职责 |
|------|------|
| `deploy.sh` | 一键部署：`up` / `rebuild` / `down` / `logs` / `ps` / `reinit` |
| `docker-compose.yml` | 服务编排，backend 显式注入 `APP_ENV=production` + `env_file` |
| `backend.Dockerfile` | Python 3.13 镜像，安装依赖并运行 Uvicorn |
| `frontend.Dockerfile` | Node 构建前端 + Nginx 托管静态资源与反向代理 |
| `nginx/` | Nginx 反向代理配置（`/api` → backend:8000） |
| `sql_init/` | MySQL 首次启动自动执行的建库/建表/导数据脚本 |
| `SQLBot/` | SQLBot 数据源相关配置 |
| `README.md` | 部署与双模式详细说明 |

---

### 4. doc/ — 文档

项目设计、接口与数据流文档（中文 Markdown），包括：
- 方案与实施计划（AI CDP 落地方案、ABM360 实施计划）
- 数据流与数仓（CDP 数据流、ODS→DWS 聚合逻辑、数仓同步数据形式）
- 接口文档（后端接口测试、ES 增删改查、数据同步 API、表数据监控 API）
- 功能对照（公司名去重功能对照、前端细节修复计划）

---

### 5. scripts/ — 数据库迁移与同步脚本

- `*.sql`：表结构/索引/注释的增量迁移脚本（如 `add_perf_indexes.sql`、`build_aggregation.sql`）
- `incremental_sync.sh`：增量同步脚本
- `import_key_customer.py`：关键客户数据导入

---

### 6. file/ — 数据导入与原始数据

- `create_tables_standard.py` / `fix_lead_table.py` / `import_excel_to_mysql.py`：建表、修复、Excel 导入 MySQL 的脚本
- `*.xlsx`：原始业务数据（CRM 联系人、营销线索、ICP 客户等明细）

---

### 7. skills/ — AI 编程技能

- `deploy/SKILL.md`：部署技能。封装项目部署流程，供 CodeBuddy / Trae 等 AI 工具
  在用户要求"部署/重新部署"时自动读取并按标准 SOP 执行。

---

### 8. backup/ — 备份

- `backup20260710/`：历史数据备份
- `README.md`：备份说明

---

## 快速开始

**开发模式**（本地进程）：
```bash
cd backend && APP_ENV=development uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

**生产模式**（Docker 部署，连本机 docker MySQL）：
```bash
cd deploy && sudo bash deploy.sh up
```

详见 [`deploy/README.md`](deploy/README.md)。
