# CDP ABM 360° Phase 1 — Implementation Plan

## Context

锐捷网络 CDP (Customer Data Platform) DEMO 项目，目标是为 2300 个企业彩光 ICP 客户构建 360° 客户视图系统。Phase 1 覆盖 P0+P1 功能（重点 P0），包括 360 客户列表页、客户详情页、AI 对话、专项看板、AI 审核页面。

数据源：MySQL 数据库 (192.168.159.22:33307/app_cdp) 中 11 张 ODS 表，涵盖 CRM 联系人/商机、Linkflow 联系人/事件、营销线索、官网用户、天润客服、致趣行为/联系人。

**数据拼接核心策略**：以 2239 个 CRM ICP 客户为锚点，通过三层关联键拼接全部数据：
- **Layer 1（客户名）**：CRM 商机、致趣行为/联系人、营销线索 → 直接 JOIN
- **Layer 2（手机号/邮箱）**：从 CRM 联系人提取 6456 个手机号 → 匹配 Linkflow 联系人、天润会话(visitor_mobile_phone)、官网用户、营销线索(补充)
- **Layer 3（contact_id 中转）**：Layer2 获取的 Linkflow contact_id → 查 Linkflow 事件(14M 大表，分批 IN 查询)

实测覆盖率：天润客服按客户名匹配为 0（名称不一致），但通过手机号中转可关联。Linkflow 联系人手机号匹配有数据但 name 可能不完整。

技术栈：**Vue3 + Python FastAPI + MySQL**

---

## File Structure

```
cdp/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI 入口，路由注册
│   │   ├── config.py                # 数据库配置、环境变量
│   │   ├── database.py              # SQLAlchemy 引擎、连接池
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── schemas.py           # Pydantic 响应模型
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── customer_list.py     # GET /api/customers — 列表+筛选+导出
│   │   │   ├── customer_detail.py   # GET /api/customers/{id} — 详情各 TAB
│   │   │   ├── campaign.py          # GET /api/campaign — 专项看板
│   │   │   ├── ai_chat.py           # POST /api/ai/chat — AI 对话/NL2SQL
│   │   │   └── review.py            # GET /api/review — 审核队列
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── customer_service.py  # 客户列表/详情核心业务逻辑
│   │   │   ├── interaction_service.py # 互动行为聚合
│   │   │   ├── opportunity_service.py # 商机聚合
│   │   │   ├── scoring_service.py   # 意向分/阶段/角色覆盖计算
│   │   │   ├── ai_service.py        # NL2SQL + LLM 调用
│   │   │   ├── export_service.py    # Excel 导出
│   │   │   └── campaign_service.py  # 专项看板聚合
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── company_match.py     # 公司名称标准化/相似度
│   │       └── role_mapper.py       # 采购角色→四类关键角色映射
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── router/
│   │   │   └── index.js             # 路由配置
│   │   ├── stores/
│   │   │   ├── customer.js          # 客户列表状态
│   │   │   └── filters.js           # 筛选条件状态
│   │   ├── api/
│   │   │   └── index.js             # Axios 实例 + API 封装
│   │   ├── views/
│   │   │   ├── CustomerList.vue     # 360 客户列表页
│   │   │   ├── CustomerDetail.vue   # 客户详情页（含 TAB 切换）
│   │   │   ├── CampaignBoard.vue    # 专项效果看板
│   │   │   ├── AiChat.vue           # AI 对话页
│   │   │   └── ReviewQueue.vue      # AI 审核队列
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── AppSidebar.vue
│   │   │   │   └── AppTopbar.vue
│   │   │   ├── customer/
│   │   │   │   ├── CustomerTable.vue
│   │   │   │   ├── FilterBar.vue
│   │   │   │   └── ExportButton.vue
│   │   │   ├── detail/
│   │   │   │   ├── OverviewTab.vue
│   │   │   │   ├── ContactsTab.vue
│   │   │   │   ├── KpiCards.vue
│   │   │   │   ├── CustomerProfile.vue
│   │   │   │   ├── BusinessTags.vue
│   │   │   │   ├── FollowupStatus.vue
│   │   │   │   ├── OpportunityBudget.vue
│   │   │   │   ├── BehaviorTimeline.vue
│   │   │   │   ├── AiInsight.vue
│   │   │   │   ├── ContactCard.vue
│   │   │   │   └── AiPriorityContact.vue
│   │   │   ├── campaign/
│   │   │   │   ├── CampaignKpis.vue
│   │   │   │   ├── OpportunityFunnel.vue
│   │   │   │   ├── ChannelPie.vue
│   │   │   │   ├── StageDistChart.vue
│   │   │   │   ├── RoleCoverageChart.vue
│   │   │   │   ├── ContentTable.vue
│   │   │   │   └── FollowupTable.vue
│   │   │   ├── ai/
│   │   │   │   ├── ChatThread.vue
│   │   │   │   ├── EntityChips.vue
│   │   │   │   ├── QueryResultTable.vue
│   │   │   │   └── ExampleQueries.vue
│   │   │   └── review/
│   │   │       ├── ReviewSummary.vue
│   │   │       └── ReviewItem.vue
│   │   └── styles/
│   │       └── main.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
└── scripts/
    ├── build_aggregation.sql         # 聚合表 DDL + 填充
    └── init_data.py                  # 数据初始化脚本
```

---

## Phase 1: 项目初始化与数据层 (Tasks 1-4)

### Task 1: 后端项目脚手架

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/.env`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/main.py`

- [ ] **Step 1: 创建 requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
pymysql==1.1.1
pandas==2.2.3
python-dotenv==1.0.1
pydantic==2.9.2
openpyxl==3.1.5
httpx==0.27.2
```

- [ ] **Step 2: 创建 .env**

```
DB_HOST=192.168.159.22
DB_PORT=33307
DB_USER=app_cdp
DB_PASSWORD=123456
DB_NAME=app_cdp
LLM_API_KEY=
LLM_BASE_URL=
```

- [ ] **Step 3: 创建 config.py**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_host: str = "192.168.159.22"
    db_port: int = 33307
    db_user: str = "app_cdp"
    db_password: str = "123456"
    db_name: str = "app_cdp"
    llm_api_key: str = ""
    llm_base_url: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 4: 创建 database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

DATABASE_URL = (
    f"mysql+pymysql://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    f"?charset=utf8mb4"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 5: 创建 main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="CDP ABM 360 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 6: 安装依赖并启动**

Run: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`
Expected: `Uvicorn running on http://127.0.0.1:8000`
Verify: `curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`

- [ ] **Step 7: Commit**

```bash
git init && git add -A && git commit -m "feat: init FastAPI backend scaffold with DB connection"
```

---

### Task 2: 前端项目脚手架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router/index.js`
- Create: `frontend/src/api/index.js`
- Create: `frontend/src/styles/main.css`

- [ ] **Step 1: 初始化 Vue3 项目**

Run: `npm create vite@latest frontend -- --template vue`
Then: `cd frontend && npm install`

- [ ] **Step 2: 安装依赖**

Run: `cd frontend && npm install vue-router@4 pinia axios echarts vue-echarts @tailwindcss/vite tailwindcss`

- [ ] **Step 3: 配置 vite.config.js**

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 4: 配置 router/index.js**

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/customers' },
  { path: '/customers', name: 'CustomerList', component: () => import('../views/CustomerList.vue') },
  { path: '/customers/:id', name: 'CustomerDetail', component: () => import('../views/CustomerDetail.vue') },
  { path: '/campaign', name: 'CampaignBoard', component: () => import('../views/CampaignBoard.vue') },
  { path: '/ai-chat', name: 'AiChat', component: () => import('../views/AiChat.vue') },
  { path: '/review', name: 'ReviewQueue', component: () => import('../views/ReviewQueue.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
```

- [ ] **Step 5: 创建 api/index.js**

```javascript
import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

export const customerApi = {
  getList: (params) => api.get('/customers', { params }),
  getDetail: (id) => api.get(`/customers/${id}`),
  getContacts: (id) => api.get(`/customers/${id}/contacts`),
  getInteractions: (id, params) => api.get(`/customers/${id}/interactions`, { params }),
  getOpportunities: (id) => api.get(`/customers/${id}/opportunities`),
  getAiInsight: (id) => api.get(`/customers/${id}/ai-insight`),
}

export const campaignApi = {
  getDashboard: (params) => api.get('/campaign', { params }),
}

export const aiApi = {
  chat: (data) => api.post('/ai/chat', data),
  parseQuery: (text) => api.post('/ai/parse', { text }),
}

export const reviewApi = {
  getList: (params) => api.get('/review', { params }),
  confirm: (id, data) => api.post(`/review/${id}/confirm`, data),
}

export const exportApi = {
  customers: (params) => api.get('/customers/export', { params, responseType: 'blob' }),
}

export default api
```

- [ ] **Step 6: 配置 styles/main.css（Tailwind 入口 + 自定义暗色主题）**

```css
@import "tailwindcss";

:root {
  --bg0: #04070f;
  --bg1: #0a101b;
  --panel: rgba(12,17,28,.84);
  --text: #edf2fb;
  --muted: #9aa8c2;
  --brand: #65b3ff;
  --ok: #34d399;
  --warn: #fbbf24;
  --bad: #fb7185;
  --line: rgba(43,56,84,.92);
}

body {
  margin: 0;
  background: linear-gradient(180deg, var(--bg0), var(--bg1));
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
```

- [ ] **Step 7: 创建 App.vue 基础布局**

```html
<template>
  <div class="flex h-screen">
    <AppSidebar />
    <main class="flex-1 overflow-auto">
      <AppTopbar />
      <div class="p-6">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import AppSidebar from './components/layout/AppSidebar.vue'
import AppTopbar from './components/layout/AppTopbar.vue'
</script>
```

- [ ] **Step 8: 创建 AppSidebar.vue**

```html
<template>
  <aside class="w-[280px] border-r border-[var(--line)] bg-[rgba(10,18,32,.96)] p-4 flex flex-col">
    <div class="flex items-center gap-3 p-3 mb-4 border border-white/5 rounded-2xl bg-[rgba(15,23,39,.88)]">
      <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-[var(--brand)] to-[#2dd4bf]"></div>
      <div>
        <div class="text-sm font-bold">锐捷｜CDP MVP</div>
        <div class="text-xs text-[var(--muted)]">Phase 1</div>
      </div>
    </div>
    <div class="text-xs text-[var(--muted)] mb-2 px-2">业务模块</div>
    <nav class="flex flex-col gap-1">
      <router-link v-for="item in navItems" :key="item.path" :to="item.path"
        class="flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm transition-all"
        :class="$route.path.startsWith(item.path) ? 'bg-[rgba(90,179,255,.15)] text-white' : 'text-[var(--muted)] hover:bg-white/5'">
        <span class="w-2 h-2 rounded-full" :class="$route.path.startsWith(item.path) ? 'bg-[var(--brand)]' : 'bg-[var(--muted)]/30'"></span>
        {{ item.label }}
      </router-link>
    </nav>
  </aside>
</template>

<script setup>
const navItems = [
  { path: '/customers', label: 'ABM 客户360°' },
  { path: '/campaign', label: '专项效果看板' },
  { path: '/ai-chat', label: 'AI 对话分析' },
  { path: '/review', label: '人工审核队列' },
]
</script>
```

- [ ] **Step 9: 创建 AppTopbar.vue**

```html
<template>
  <div class="flex items-center justify-between px-6 py-4 border-b border-[var(--line)]">
    <div>
      <div class="text-xs text-[var(--muted)] tracking-wide">Growth Intelligence Surface</div>
      <h1 class="text-xl font-bold mt-1">{{ title }}</h1>
    </div>
    <div class="flex items-center gap-3">
      <button class="px-3 py-1.5 text-xs rounded-lg border border-[var(--line)] bg-white/5 hover:bg-white/10 transition"
        @click="$emit('action')">
        {{ actionLabel }}
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({ title: String, actionLabel: { type: String, default: '导出' } })
defineEmits(['action'])
</script>
```

- [ ] **Step 10: 创建 main.js 并配置 Pinia**

```javascript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/main.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

- [ ] **Step 11: 启动并验证**

Run: `cd frontend && npm run dev`
Expected: `Local: http://localhost:3000/`
Verify: 浏览器打开 http://localhost:3000 → 显示带侧边栏的空页面

- [ ] **Step 12: Commit**

```bash
git add frontend/ && git commit -m "feat: init Vue3 frontend with router, sidebar, topbar"
```

---

### Task 3: 数据拼接策略 + 增量 ETL 表设计

**架构**：数仓推送数据到 ODS 表 → 后端定时任务增量抽取(etl_time) → 三层拼接写入 DWS 表 → 应用查询 DWS

**核心问题**：11 张 ODS 表之间客户名称不一致（实测天润客服 vs CRM 客户名匹配为 0），必须以 **手机号 + 邮箱 + 客户名** 三条关联键做三层拼接。

**增量策略**：
- **小表全量刷新**（< 10万行，秒级完成）：CRM联系人(6K)、CRM商机(52K)、致趣联系人(2K)、营销线索(35K)
- **大表增量抽取**（按 etl_time 过滤）：致趣行为(303K)、天润会话(777K)、Linkflow事件(14M)
- **增量逻辑**：记录每张表上次同步时间 → 查 `WHERE etl_time > :last_sync` → 拼接 → UPSERT 到 DWS

**实测数据关联覆盖率：**
```
CRM 联系人表: 2239 客户, 6456 个手机号, 655 个邮箱 ← 基础锚点
  ├─ 按客户名 → CRM商机(52K)          ✅ 直接匹配
  ├─ 按客户名 → 致趣行为(303K)        ✅ 中国恩菲有15条
  ├─ 按客户名 → 致趣联系人(2307)      ✅ 868手机号交叉
  ├─ 按客户名 → 营销线索(35K)         ✅ 东华工程有匹配
  ├─ 按手机号 → Linkflow联系人(75K)   ⚠️ 有匹配但name可能不完整
  ├─ 按手机号 → Linkflow事件(14M)     ⚠️ 需contact_id中转
  ├─ 按手机号 → 天润会话(777K)        ⚠️ 通过visitor_mobile_phone
  ├─ 按手机号 → 官网用户(130K)        ⚠️ 通过mobile_phone
  ├─ 按手机号 → 营销线索(35K)         ✅ 双重匹配增强
  ├─ 按客户名 → 天润会话              ❌ 名称不一致
  └─ 按客户名 → 天润客户资料          ❌ 名称不一致
```

**三层拼接架构：**

```
Layer 1 — 客户名直接匹配（小表，快速）
  ods_crm_opportunity_day    .customer_name  = 客户池.customer_name
  ods_zhique_contact_day     .related_company = 客户池.customer_name
  ods_zhique_behavior_list_day.company_name   = 客户池.customer_name
  ods_marketing_lead_day     .customer_company = 客户池.customer_name

Layer 2 — 手机号/邮箱匹配（中表，需先建映射）
  先构建: 客户 → [手机号集合, 邮箱集合] （来自CRM联系人）
  再用手机号匹配:
    ods_linkflow_contacts_day .mobile_phone ∈ 客户手机号集合
    ods_ruijie_website_user_day.mobile_phone ∈ 客户手机号集合
    ods_tianrun_session_day   .visitor_mobile_phone ∈ 客户手机号集合
    ods_marketing_lead_day    .contact_phone ∈ 客户手机号集合（补充Layer1）

Layer 3 — contact_id 中转（大表14M，必须先筛再查）
  从Layer2获取: Linkflow contact_ids
  ods_linkflow_events_day    .contact_id ∈ 客户Linkflow contact_ids
```

- [ ] **Step 1: 创建聚合表 DDL（含联系人映射表）**

**Files:**
- Create: `scripts/build_aggregation.sql`

```sql
-- ============================================
-- 0. 同步状态追踪表（每张 ODS 表的上次同步时间）
-- ============================================
CREATE TABLE IF NOT EXISTS dws_sync_meta (
  table_name VARCHAR(128) PRIMARY KEY,
  last_sync_time DATETIME NOT NULL COMMENT '上次同步的 etl_time 截止点',
  last_run_time DATETIME NOT NULL COMMENT '上次执行时间',
  rows_synced INT DEFAULT 0,
  status VARCHAR(16) DEFAULT 'success'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='增量同步状态追踪';

-- ============================================
-- 1. 联系人映射表（UNIQUE KEY 支持 UPSERT）
-- ============================================
CREATE TABLE IF NOT EXISTS dws_contact_mapping (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  contact_name VARCHAR(128),
  mobile VARCHAR(64),
  email VARCHAR(255),
  department VARCHAR(128),
  position VARCHAR(128),
  purchase_role VARCHAR(64),
  role_category VARCHAR(32),
  source_table VARCHAR(64),
  linkflow_contact_id BIGINT,
  zhique_matched TINYINT DEFAULT 0,
  etl_time DATETIME COMMENT '源表最新 etl_time',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_customer_mobile (customer_name, mobile),
  INDEX idx_mobile (mobile),
  INDEX idx_linkflow_id (linkflow_contact_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='联系人跨系统映射表';

-- ============================================
-- 2. 客户360聚合主表（UNIQUE KEY 支持 UPSERT）
-- ============================================
CREATE TABLE IF NOT EXISTS dws_customer_360 (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  industry VARCHAR(128),
  region VARCHAR(128),
  owner_name VARCHAR(128),
  campaign_tag VARCHAR(255) DEFAULT '企业彩光ICT',
  purchase_stage VARCHAR(64),
  forecast_type VARCHAR(64),
  role_coverage VARCHAR(16),
  role_detail JSON,
  intent_score INT DEFAULT 0,
  intent_level VARCHAR(16),
  interaction_count_30d INT DEFAULT 0,
  interaction_count_total INT DEFAULT 0,
  last_interaction_time DATETIME,
  last_interaction_channel VARCHAR(64),
  top_channels JSON,
  active_opp_count INT DEFAULT 0,
  active_opp_amount DECIMAL(20,4) DEFAULT 0,
  funnel_opp_count INT DEFAULT 0,
  won_amount DECIMAL(20,4) DEFAULT 0,
  highest_stage_opp JSON,
  contact_count INT DEFAULT 0,
  mobile_count INT DEFAULT 0,
  product_categories JSON,
  is_existing_customer TINYINT DEFAULT 0,
  source_tables JSON,
  data_coverage JSON,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_customer_name (customer_name),
  INDEX idx_industry (industry),
  INDEX idx_owner (owner_name),
  INDEX idx_intent (intent_level),
  INDEX idx_stage (purchase_stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户360聚合主表';

-- ============================================
-- 3. 联系人聚合表
-- ============================================
CREATE TABLE IF NOT EXISTS dws_contact_360 (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_id BIGINT NOT NULL,
  contact_name VARCHAR(128),
  mobile VARCHAR(64),
  email VARCHAR(255),
  department VARCHAR(128),
  position VARCHAR(128),
  purchase_role VARCHAR(64),
  role_category VARCHAR(32),
  interaction_count INT DEFAULT 0,
  interaction_count_30d INT DEFAULT 0,
  last_interaction_time DATETIME,
  top_content_types JSON,
  product_interests JSON,
  activity_level VARCHAR(16),
  intent_level VARCHAR(16),
  lead_stage VARCHAR(64),
  source_tables JSON,
  linkflow_contact_id BIGINT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_customer_mobile (customer_id, mobile),
  INDEX idx_role (role_category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='联系人聚合表';

-- ============================================
-- 4. 互动行为明细表（UNIQUE KEY 去重 + UPSERT）
-- ============================================
CREATE TABLE IF NOT EXISTS dws_interaction_detail (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  contact_name VARCHAR(128),
  mobile VARCHAR(64),
  source_table VARCHAR(64),
  channel VARCHAR(64),
  behavior_type VARCHAR(128),
  content VARCHAR(512),
  event_time DATETIME,
  is_high_value TINYINT DEFAULT 0,
  source_id BIGINT COMMENT '源表主键ID，用于去重',
  etl_time DATETIME,
  UNIQUE KEY uk_source_id (source_table, source_id),
  INDEX idx_customer (customer_name),
  INDEX idx_mobile (mobile),
  INDEX idx_time (event_time),
  INDEX idx_channel (channel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='互动行为明细预聚合表';

-- ============================================
-- 5. 审核队列表
-- ============================================
CREATE TABLE IF NOT EXISTS dws_review_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  review_type VARCHAR(32) NOT NULL,
  candidate_a VARCHAR(500),
  candidate_b VARCHAR(500),
  match_score DECIMAL(5,2),
  evidence JSON,
  status VARCHAR(16) DEFAULT 'pending',
  reviewer VARCHAR(64),
  reviewed_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_status (status),
  INDEX idx_type (review_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审核队列';
```

- [ ] **Step 2: 执行 DDL**

Run: `mysql -h 192.168.159.22 -u app_cdp -p123456 -P 33307 app_cdp --default-character-set=utf8mb4 < scripts/build_aggregation.sql`

- [ ] **Step 3: Commit**

```bash
git add scripts/ && git commit -m "feat: aggregation DDL with contact mapping and interaction detail tables"
```

---

### Task 4: 定时增量 ETL 服务

**Files:**
- Create: `backend/app/services/etl_sync.py` — 增量同步核心逻辑
- Create: `backend/app/services/etl_scheduler.py` — APScheduler 定时任务
- Modify: `backend/app/main.py` — 注册 scheduler 启动/关闭

**ETL 执行流程（每次定时触发）：**
```
1. 读 dws_sync_meta 获取各表 last_sync_time
2. Layer 1 小表全量刷新（CRM联系人/商机、致趣联系人、营销线索）
3. Layer 1 大表增量（致趣行为 WHERE etl_time > last_sync）
4. Layer 2 按手机号增量匹配（天润会话、Linkflow联系人、官网用户）
5. Layer 3 Linkflow事件增量（etl_time > last_sync，用已知contact_id过滤）
6. UPSERT 到 dws_interaction_detail / dws_contact_mapping
7. 重算受影响客户的 dws_customer_360 / dws_contact_360 聚合
8. 更新 dws_sync_meta
```

- [ ] **Step 1: 创建 etl_sync.py — 增量同步核心**

```python
"""
增量 ETL 同步服务
- 小表全量刷新（<10万行）
- 大表按 etl_time 增量抽取
- UPSERT 到 DWS 聚合表
"""
import pymysql
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "192.168.159.22", "port": 33307,
    "user": "app_cdp", "password": "123456",
    "database": "app_cdp", "charset": "utf8mb4",
}

BATCH_SIZE = 500

ROLE_CATEGORIES = {
    "拍板者": "拍板者", "决策者": "决策者",
    "评估者": "评估者", "使用者": "采购推动者",
    "其他": "普通", "未知": "普通",
}
HIGH_VALUE = {"单页面表单提交", "submit_project_consult", "register",
              "submit_question", "submit_service", "click_consult"}

STAGE_MAP = {
    "阶段0：未接触上客户": "未接触",
    "阶段1：接触上客户，初步交流；": "问题识别",
    "阶段2：正式交流，价值认可": "解决方案探索",
    "阶段3：测试/入围，愿意尝试": "解决方案探索",
    "阶段4：拿到门票，进入招投标": "需求构建",
    "阶段5：已中标，等待采购": "需求构建",
    "阶段6：完成采购，实现进入": "已完成",
}
FORECAST_STAGE = {
    "线索": "问题识别", "机会-": "问题识别", "机会": "问题识别",
    "机会+": "解决方案探索", "可能-": "解决方案探索",
    "可能": "需求构建", "可能+": "需求构建",
    "优势": "需求构建", "确保": "需求构建",
}

def classify_channel(bt):
    if bt in ("打开邮件", "点击邮件链接"): return "邮件"
    if bt in ("观看直播", "报名会议", "参会"): return "直播"
    if bt in ("单页面表单提交",): return "表单"
    return "官网"

def get_conn():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)

def batch_query(cur, sql_tpl, values):
    """分批 IN 查询"""
    results = []
    for i in range(0, len(values), BATCH_SIZE):
        batch = values[i:i+BATCH_SIZE]
        sql = sql_tpl.format(ph=",".join(["%s"]*len(batch)))
        cur.execute(sql, batch)
        results.extend(cur.fetchall())
    return results

# ── 同步状态管理 ──
def get_last_sync(cur, table_name):
    cur.execute("SELECT last_sync_time FROM dws_sync_meta WHERE table_name = %s", (table_name,))
    row = cur.fetchone()
    return row["last_sync_time"] if row else datetime(2020, 1, 1)

def update_sync_meta(cur, table_name, last_sync_time, rows_synced, status="success"):
    cur.execute("""
        INSERT INTO dws_sync_meta (table_name, last_sync_time, last_run_time, rows_synced, status)
        VALUES (%s, %s, NOW(), %s, %s)
        ON DUPLICATE KEY UPDATE
            last_sync_time = VALUES(last_sync_time),
            last_run_time = NOW(),
            rows_synced = VALUES(rows_synced),
            status = VALUES(status)
    """, (table_name, last_sync_time, rows_synced, status))

# ── 增量抽取函数 ──
def sync_small_table_full(cur, table_name, sql):
    """小表全量刷新"""
    cur.execute(sql)
    rows = cur.fetchall()
    logger.info(f"  {table_name}: 全量 {len(rows)} 行")
    return rows

def sync_large_table_incremental(cur, table_name, sql_tpl, last_sync):
    """大表增量：WHERE etl_time > last_sync"""
    sql = sql_tpl + " AND etl_time > %s ORDER BY etl_time"
    cur.execute(sql, (last_sync,))
    rows = cur.fetchall()
    max_etl = max((r.get("etl_time") for r in rows if r.get("etl_time")), default=last_sync)
    logger.info(f"  {table_name}: 增量 {len(rows)} 行 (since {last_sync})")
    return rows, max_etl

# ── UPSERT 互动明细 ──
def upsert_interactions(cur, interactions):
    """INSERT ... ON DUPLICATE KEY UPDATE 互动记录"""
    if not interactions:
        return 0
    sql = """
        INSERT INTO dws_interaction_detail
        (customer_name, contact_name, mobile, source_table, channel,
         behavior_type, content, event_time, is_high_value, source_id, etl_time)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            channel = VALUES(channel), content = VALUES(content),
            event_time = VALUES(event_time), is_high_value = VALUES(is_high_value)
    """
    cur.executemany(sql, interactions)
    return len(interactions)

# ── 重算客户聚合 ──
def refresh_customer_aggregate(cur, affected_customers):
    """对受影响的客户重新聚合 dws_customer_360"""
    if not affected_customers:
        return 0
    now = datetime.now()
    thirty_days_ago = now - timedelta(days=30)
    refreshed = 0

    for cname in affected_customers:
        # 从 interaction_detail 汇总
        cur.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN event_time >= %s THEN 1 ELSE 0 END) as recent,
                   MAX(event_time) as last_time
            FROM dws_interaction_detail WHERE customer_name = %s
        """, (thirty_days_ago, cname))
        stats = cur.fetchone()

        # 渠道分布
        cur.execute("""
            SELECT channel, COUNT(*) as cnt FROM dws_interaction_detail
            WHERE customer_name = %s GROUP BY channel
        """, (cname,))
        channels = {r["channel"]: r["cnt"] for r in cur.fetchall()}

        # 最近互动渠道
        last_channel = None
        if stats["last_time"]:
            cur.execute("""
                SELECT channel FROM dws_interaction_detail
                WHERE customer_name = %s AND event_time = %s LIMIT 1
            """, (cname, stats["last_time"]))
            r = cur.fetchone()
            if r: last_channel = r["channel"]

        # 商机
        cur.execute("""
            SELECT * FROM ods_crm_opportunity_day WHERE customer_name = %s
        """, (cname,))
        opps = cur.fetchall()

        lost = ("已丢单","客户取消采购计划","7、客户取消采购计划","8、已丢单")
        active = [o for o in opps if not o.get("is_cancel_lost") or o["is_cancel_lost"] not in lost]
        active_amt = sum(float(o.get("amount_10k") or 0) for o in active)
        funnel = [o for o in active if o.get("is_funnel") == "是"]
        won = sum(float(o.get("actual_order_amount_10k") or 0) for o in opps
                  if o.get("actual_order_amount_10k") and float(o["actual_order_amount_10k"]) > 0)

        # 阶段
        best_idx, best_stage, best_ft = -1, "未知", ""
        order = ["未接触","问题识别","解决方案探索","需求构建","已完成"]
        for o in opps:
            cs = o.get("customer_stage") or ""
            ft = o.get("forecast_type") or ""
            s = STAGE_MAP.get(cs, FORECAST_STAGE.get(ft, "未知"))
            idx = order.index(s) if s in order else -1
            if idx > best_idx: best_idx, best_stage, best_ft = idx, s, ft

        # 角色覆盖
        cur.execute("SELECT purchase_role FROM dws_contact_mapping WHERE customer_name = %s", (cname,))
        roles = set()
        for r in cur.fetchall():
            cat = ROLE_CATEGORIES.get(r.get("purchase_role",""), "普通")
            if cat in ("拍板者","决策者","评估者","采购推动者"): roles.add(cat)

        # 意向分
        intent = 0
        for o in opps:
            ft = o.get("forecast_type","")
            intent += {"确保":30,"优势":25,"可能+":20,"可能":10,"可能-":10,"机会+":5}.get(ft, 0)
        intent += min((stats["recent"] or 0) * 2, 30)
        cur.execute("SELECT COUNT(*) as hv FROM dws_interaction_detail WHERE customer_name=%s AND is_high_value=1", (cname,))
        intent += cur.fetchone()["hv"] * 8
        intent = min(intent, 100)
        intent_level = "高" if intent >= 70 else ("中" if intent >= 40 else "低")

        # 行业/负责人/区域
        cur.execute("SELECT industry, owner_name, region FROM dws_customer_360 WHERE customer_name=%s", (cname,))
        existing = cur.fetchone() or {}
        industry = existing.get("industry")
        if not industry:
            for o in opps:
                if o.get("industry"): industry = o["industry"]; break
        owner = existing.get("owner_name")
        if not owner:
            oc = Counter(o.get("owner_name") for o in opps if o.get("owner_name"))
            owner = oc.most_common(1)[0][0] if oc else None
        region = existing.get("region")

        # 联系人/手机号数
        cur.execute("SELECT COUNT(*) as cc FROM dws_contact_mapping WHERE customer_name=%s", (cname,))
        contact_count = cur.fetchone()["cc"]
        cur.execute("SELECT COUNT(DISTINCT mobile) as mc FROM dws_contact_mapping WHERE customer_name=%s AND mobile IS NOT NULL", (cname,))
        mobile_count = cur.fetchone()["mc"]

        # 产品线
        products = list(set(o.get("product_category") for o in opps if o.get("product_category")))

        # UPSERT
        cur.execute("""
            INSERT INTO dws_customer_360
            (customer_name, industry, region, owner_name, purchase_stage, forecast_type,
             role_coverage, role_detail, intent_score, intent_level,
             interaction_count_30d, interaction_count_total,
             last_interaction_time, last_interaction_channel, top_channels,
             active_opp_count, active_opp_amount, funnel_opp_count, won_amount,
             contact_count, mobile_count, product_categories, is_existing_customer,
             source_tables, data_coverage)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                industry=VALUES(industry), region=VALUES(region), owner_name=VALUES(owner_name),
                purchase_stage=VALUES(purchase_stage), forecast_type=VALUES(forecast_type),
                role_coverage=VALUES(role_coverage), role_detail=VALUES(role_detail),
                intent_score=VALUES(intent_score), intent_level=VALUES(intent_level),
                interaction_count_30d=VALUES(interaction_count_30d),
                interaction_count_total=VALUES(interaction_count_total),
                last_interaction_time=VALUES(last_interaction_time),
                last_interaction_channel=VALUES(last_interaction_channel),
                top_channels=VALUES(top_channels),
                active_opp_count=VALUES(active_opp_count), active_opp_amount=VALUES(active_opp_amount),
                funnel_opp_count=VALUES(funnel_opp_count), won_amount=VALUES(won_amount),
                contact_count=VALUES(contact_count), mobile_count=VALUES(mobile_count),
                product_categories=VALUES(product_categories),
                is_existing_customer=VALUES(is_existing_customer),
                source_tables=VALUES(source_tables), data_coverage=VALUES(data_coverage)
        """, (
            cname, industry, region, owner, best_stage, best_ft,
            f"{len(roles)}/4", json.dumps(list(roles), ensure_ascii=False),
            intent, intent_level,
            stats["recent"] or 0, stats["total"] or 0,
            stats["last_time"], last_channel,
            json.dumps(channels, ensure_ascii=False),
            len(active), active_amt, len(funnel), won,
            contact_count, mobile_count,
            json.dumps(products, ensure_ascii=False), 1 if won > 0 else 0,
            json.dumps(["ods_crm_contact_day","ods_crm_opportunity_day"], ensure_ascii=False),
            json.dumps({"interactions": stats["total"] or 0}, ensure_ascii=False),
        ))
        refreshed += 1

    return refreshed

# ═══════════════════════════════════════
# 主 ETL 流程
# ═══════════════════════════════════════
def run_etl():
    """执行一轮增量 ETL"""
    conn = get_conn()
    cur = conn.cursor()
    start = datetime.now()
    logger.info(f"ETL 开始: {start}")
    affected_customers = set()

    try:
        # ── 1. 小表全量：CRM 联系人 ──
        crm_contacts = sync_small_table_full(cur, "ods_crm_contact_day",
            "SELECT customer_name, contact_name, mobile, email, department, "
            "position, purchase_role, industry, sales_name, etl_time "
            "FROM ods_crm_contact_day WHERE customer_name IS NOT NULL AND customer_name != ''")
        
        # UPSERT 联系人映射
        for c in crm_contacts:
            role_cat = ROLE_CATEGORIES.get(c.get("purchase_role",""), "普通")
            cur.execute("""
                INSERT INTO dws_contact_mapping
                (customer_name, contact_name, mobile, email, department, position,
                 purchase_role, role_category, source_table, etl_time)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ods_crm_contact_day',%s)
                ON DUPLICATE KEY UPDATE
                    contact_name=VALUES(contact_name), email=VALUES(email),
                    department=VALUES(department), position=VALUES(position),
                    purchase_role=VALUES(purchase_role), role_category=VALUES(role_category),
                    etl_time=VALUES(etl_time)
            """, (c["customer_name"], c["contact_name"], c["mobile"], c["email"],
                  c["department"], c["position"], c["purchase_role"], role_cat, c["etl_time"]))
            affected_customers.add(c["customer_name"])
        
        max_etl = max((c["etl_time"] for c in crm_contacts if c.get("etl_time")), default=start)
        update_sync_meta(cur, "ods_crm_contact_day", max_etl, len(crm_contacts))

        # 构建手机号映射（后续Layer2需要）
        cur.execute("SELECT customer_name, mobile FROM dws_contact_mapping WHERE mobile IS NOT NULL")
        mobile_to_customer = {r["mobile"]: r["customer_name"] for r in cur.fetchall()}
        all_mobiles = list(mobile_to_customer.keys())
        customer_names = list(set(r["customer_name"] for r in crm_contacts))

        # ── 2. 小表全量：CRM 商机 ──
        opps = sync_small_table_full(cur, "ods_crm_opportunity_day",
            "SELECT customer_name, owner_name, industry, region, etl_time "
            "FROM ods_crm_opportunity_day WHERE customer_name IN (" +
            ",".join(["%s"]*len(customer_names)) + ")")
        # 商机聚合在 refresh_customer_aggregate 中处理
        max_etl = max((o["etl_time"] for o in opps if o.get("etl_time")), default=start)
        update_sync_meta(cur, "ods_crm_opportunity_day", max_etl, len(opps))

        # ── 3. 小表全量：致趣联系人 ──
        zcontacts = sync_small_table_full(cur, "ods_zhique_contact_day",
            "SELECT related_company, contact_name, mobile, email, etl_time "
            "FROM ods_zhique_contact_day WHERE related_company IN (" +
            ",".join(["%s"]*len(customer_names)) + ")")
        max_etl = max((z["etl_time"] for z in zcontacts if z.get("etl_time")), default=start)
        update_sync_meta(cur, "ods_zhique_contact_day", max_etl, len(zcontacts))

        # ── 4. 小表全量：营销线索 ──
        leads = sync_small_table_full(cur, "ods_marketing_lead_day",
            "SELECT customer_company, contact_phone, industry, province, etl_time "
            "FROM ods_marketing_lead_day WHERE customer_company IN (" +
            ",".join(["%s"]*len(customer_names)) + ")")
        max_etl = max((l["etl_time"] for l in leads if l.get("etl_time")), default=start)
        update_sync_meta(cur, "ods_marketing_lead_day", max_etl, len(leads))

        # ── 5. 大表增量：致趣行为 ──
        last_sync_zhique = get_last_sync(cur, "ods_zhique_behavior_list_day")
        zbehaviors, max_etl_z = sync_large_table_incremental(cur, "ods_zhique_behavior_list_day",
            "SELECT id, company_name, contact_name, mobile_phone, "
            "behavior_type, behavior_name, behavior_time, etl_time "
            "FROM ods_zhique_behavior_list_day WHERE company_name IN (" +
            ",".join(["%s"]*len(customer_names)) + ")",
            last_sync_zhique)
        
        # UPSERT 互动明细
        interactions = []
        for b in zbehaviors:
            bt = b.get("behavior_type", "")
            interactions.append((
                b["company_name"], b.get("contact_name"), b.get("mobile_phone"),
                "ods_zhique_behavior_list_day", classify_channel(bt),
                bt, b.get("behavior_name"), b.get("behavior_time"),
                1 if bt in HIGH_VALUE or b.get("behavior_name") in HIGH_VALUE else 0,
                b["id"], b.get("etl_time"),
            ))
            affected_customers.add(b["company_name"])
        upsert_interactions(cur, interactions)
        update_sync_meta(cur, "ods_zhique_behavior_list_day", max_etl_z, len(zbehaviors))

        # ── 6. 大表增量：天润会话（按手机号匹配） ──
        last_sync_tianrun = get_last_sync(cur, "ods_tianrun_session_day")
        tianrun, max_etl_t = sync_large_table_incremental(cur, "ods_tianrun_session_day",
            "SELECT id, visitor_mobile_phone, visitor_name, contact_type_name, "
            "start_time_sec, total_duration_pretty, etl_time "
            "FROM ods_tianrun_session_day WHERE visitor_mobile_phone IN (" +
            ",".join(["%s"]*len(all_mobiles)) + ")",
            last_sync_tianrun)
        
        interactions_t = []
        for t in tianrun:
            cname = mobile_to_customer.get(t["visitor_mobile_phone"])
            if not cname: continue
            ts = t.get("start_time_sec")
            event_time = datetime.fromtimestamp(ts) if ts else None
            interactions_t.append((
                cname, t.get("visitor_name"), t["visitor_mobile_phone"],
                "ods_tianrun_session_day", "客服",
                t.get("contact_type_name"), f"会话: {t.get('total_duration_pretty','-')}",
                event_time, 0, t["id"], t.get("etl_time"),
            ))
            affected_customers.add(cname)
        upsert_interactions(cur, interactions_t)
        update_sync_meta(cur, "ods_tianrun_session_day", max_etl_t, len(tianrun))

        # ── 7. Layer 2: Linkflow 联系人 → 获取 contact_id ──
        lf_contacts = batch_query(cur,
            "SELECT contact_id, mobile_phone, name FROM ods_linkflow_contacts_day "
            "WHERE mobile_phone IN ({ph})",
            all_mobiles)
        lf_id_to_customer = {}
        for lc in lf_contacts:
            cname = mobile_to_customer.get(lc["mobile_phone"])
            if cname and lc.get("contact_id"):
                lf_id_to_customer[lc["contact_id"]] = cname
            # 更新 contact_mapping 的 linkflow_contact_id
            cur.execute("""
                UPDATE dws_contact_mapping SET linkflow_contact_id = %s
                WHERE mobile = %s
            """, (lc["contact_id"], lc["mobile_phone"]))

        # ── 8. 大表增量：Linkflow 事件 ──
        last_sync_lf = get_last_sync(cur, "ods_linkflow_events_day")
        all_lf_ids = list(lf_id_to_customer.keys())
        if all_lf_ids:
            lf_events, max_etl_lf = sync_large_table_incremental(cur, "ods_linkflow_events_day",
                "SELECT id, contact_id, event_name, event_date_ms, date_created, etl_time "
                "FROM ods_linkflow_events_day WHERE contact_id IN (" +
                ",".join(["%s"]*len(all_lf_ids)) + ")",
                last_sync_lf)
            
            interactions_lf = []
            for e in lf_events:
                cname = lf_id_to_customer.get(e["contact_id"])
                if not cname: continue
                en = e.get("event_name", "")
                ts_ms = e.get("event_date_ms")
                event_time = datetime.fromtimestamp(ts_ms/1000) if ts_ms else e.get("date_created")
                interactions_lf.append((
                    cname, None, None,
                    "ods_linkflow_events_day", "官网" if "click" in en.lower() else "表单" if "submit" in en.lower() else "官网",
                    en, en, event_time,
                    1 if "submit" in en.lower() else 0,
                    e["id"], e.get("etl_time"),
                ))
                affected_customers.add(cname)
            upsert_interactions(cur, interactions_lf)
            update_sync_meta(cur, "ods_linkflow_events_day", max_etl_lf, len(lf_events))

        # ── 9. 重算受影响客户的聚合数据 ──
        logger.info(f"重算 {len(affected_customers)} 个客户的聚合数据...")
        refresh_customer_aggregate(cur, affected_customers)

        conn.commit()
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"ETL 完成: {elapsed:.1f}s, 影响 {len(affected_customers)} 客户")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"ETL 失败: {e}")
        raise
    finally:
        conn.close()
```

- [ ] **Step 2: 创建 etl_scheduler.py — 定时任务调度**

```python
"""
ETL 定时调度器 — 集成到 FastAPI 生命周期
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.etl_sync import run_etl
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def start_scheduler():
    """启动定时任务：每小时执行一次增量 ETL"""
    scheduler.add_job(
        run_etl,
        trigger='interval',
        hours=1,
        id='etl_sync',
        name='增量ETL同步',
        replace_existing=True,
        max_instances=1,  # 防止重叠执行
    )
    scheduler.start()
    logger.info("ETL 定时任务已启动 (每1小时)")

def stop_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("ETL 定时任务已停止")
```

- [ ] **Step 3: 注册到 FastAPI main.py**

```python
# 在 main.py 中添加
from contextlib import asynccontextmanager
from app.services.etl_scheduler import start_scheduler, stop_scheduler

@asynccontextmanager
async def lifespan(app):
    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(title="CDP ABM 360 API", version="0.1.0", lifespan=lifespan)

# 手动触发 ETL 的 API（调试用）
@app.post("/api/admin/etl/run")
def trigger_etl():
    from app.services.etl_sync import run_etl
    run_etl()
    return {"status": "ok"}
```

- [ ] **Step 4: requirements.txt 添加 apscheduler**

```
apscheduler==3.10.4
```

- [ ] **Step 5: 首次全量初始化**

首次运行需要手动触发一次全量（此时 last_sync_time 默认 2020-01-01，相当于全量）：

Run: `curl -X POST http://127.0.0.1:8000/api/admin/etl/run`

后续自动按每小时增量执行。

- [ ] **Step 6: 验证增量效果**

```sql
-- 查看各表同步状态
SELECT * FROM dws_sync_meta;

-- 查看互动明细
SELECT source_table, COUNT(*) as cnt FROM dws_interaction_detail GROUP BY source_table;

-- 查看客户聚合
SELECT customer_name, intent_level, interaction_count_total, data_coverage
FROM dws_customer_360 ORDER BY intent_score DESC LIMIT 10;
```

- [ ] **Step 7: Commit**

```bash
git add backend/ && git commit -m "feat: scheduled incremental ETL with three-layer join"
```

### Task 4b: 公司名 Embedding 聚类匹配（增量）

**目标**：跨系统公司名去重。2239 个 CRM 客户名 vs 各源约 10 万 unique 公司名，通过 Embedding + 规则 + 证据 + LLM 四步找到同一主体的不同写法。

**Files:**
- Create: `backend/app/services/company_dedup.py`
- Create: `data/company_names.db` (SQLite，只存 id + 公司名 + 来源，几 MB)

**流程（首次全量 + 后续增量）：**
```
首次：
  1. 从所有 ODS 表提取 unique 公司名 → SQLite (~10万条，几MB)
  2. 批量调 Embedding API → 内存 numpy array
  3. CRM 2239 客户名 Embedding → numpy batch cosine → top-K 候选
  4. 候选对 → rule_score + evidence_score → 高分对 → LLM 精判
  5. 三路加权 → 写入 dws_review_queue + 更新 dws_contact_mapping

增量（ETL 后触发）：
  1. 对比 SQLite 找出新增公司名（NOT IN 已有记录）
  2. 只对新增名称做 Embedding + 搜索
  3. 新候选对 → 打分 → 入审核队列
```

- [ ] **Step 1: SQLite 建库 — 提取所有源表公司名**

```python
"""data/build_company_db.py — 一次性建库 + 增量更新"""
import sqlite3
import pymysql

DB_MYSQL = {
    "host": "192.168.159.22", "port": 33307,
    "user": "app_cdp", "password": "123456",
    "database": "app_cdp", "charset": "utf8mb4",
}
SQLITE_PATH = "data/company_names.db"

# 各源表提取公司名的 SQL
SOURCE_QUERIES = [
    ("crm_contact", "SELECT DISTINCT customer_name as name FROM ods_crm_contact_day WHERE customer_name != ''"),
    ("crm_opportunity", "SELECT DISTINCT customer_name as name FROM ods_crm_opportunity_day WHERE customer_name != ''"),
    ("zhique_contact", "SELECT DISTINCT related_company as name FROM ods_zhique_contact_day WHERE related_company != ''"),
    ("zhique_behavior", "SELECT DISTINCT company_name as name FROM ods_zhique_behavior_list_day WHERE company_name != ''"),
    ("lead", "SELECT DISTINCT customer_company as name FROM ods_marketing_lead_day WHERE customer_company != ''"),
    ("lead_final", "SELECT DISTINCT final_company_name as name FROM ods_marketing_lead_day WHERE final_company_name != ''"),
    ("tianrun_session", "SELECT DISTINCT customer_name as name FROM ods_tianrun_session_day WHERE customer_name != ''"),
    ("tianrun_profile", "SELECT DISTINCT customer_name as name FROM ods_tianrun_customer_profile_day WHERE customer_name != ''"),
    ("linkflow", "SELECT DISTINCT company as name FROM ods_linkflow_contacts_day WHERE company IS NOT NULL AND company != ''"),
    ("website", "SELECT DISTINCT company_name as name FROM ods_ruijie_website_user_day WHERE company_name IS NOT NULL AND company_name != ''"),
]

def build_or_update():
    # SQLite 建表
    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            is_crm INTEGER DEFAULT 0,
            UNIQUE(name, source)
        )
    """)
    sconn.execute("CREATE INDEX IF NOT EXISTS idx_name ON companies(name)")
    
    # 从 MySQL 各表提取
    mconn = pymysql.connect(**DB_MYSQL, cursorclass=pymysql.cursors.DictCursor)
    cur = mconn.cursor()
    
    total = 0
    for source, sql in SOURCE_QUERIES:
        cur.execute(sql)
        rows = cur.fetchall()
        for r in rows:
            is_crm = 1 if source in ("crm_contact", "crm_opportunity") else 0
            sconn.execute(
                "INSERT OR IGNORE INTO companies (name, source, is_crm) VALUES (?, ?, ?)",
                (r["name"], source, is_crm)
            )
            total += 1
    
    mconn.close()
    sconn.commit()
    
    # 统计
    count = sconn.execute("SELECT COUNT(DISTINCT name) FROM companies").fetchone()[0]
    sources = sconn.execute("SELECT source, COUNT(*) FROM companies GROUP BY source").fetchall()
    sconn.close()
    
    print(f"总计: {total} 条记录, {count} 个 unique 公司名")
    for s, c in sources:
        print(f"  {s}: {c}")
    return count

def get_new_names(existing_names: set) -> list:
    """增量：获取新增的公司名"""
    sconn = sqlite3.connect(SQLITE_PATH)
    all_names = set(r[0] for r in sconn.execute("SELECT DISTINCT name FROM companies").fetchall())
    sconn.close()
    return list(all_names - existing_names)

if __name__ == "__main__":
    build_or_update()
```

- [ ] **Step 2: Embedding + numpy batch cosine 相似度搜索**

```python
"""backend/app/services/company_dedup.py"""
import numpy as np
import sqlite3
import httpx
import re
from collections import defaultdict

SQLITE_PATH = "data/company_names.db"

# ── Embedding 调用（兼容 OpenAI / 本地模型） ──
def get_embeddings(texts: list[str], api_key: str, base_url: str, model: str = "text-embedding-3-small") -> np.ndarray:
    """批量获取 embedding，自动分批（每批100条）"""
    all_embeddings = []
    for i in range(0, len(texts), 100):
        batch = texts[i:i+100]
        resp = httpx.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": batch},
            timeout=30,
        )
        data = resp.json()["data"]
        all_embeddings.extend([d["embedding"] for d in data])
    return np.array(all_embeddings, dtype=np.float32)

# ── Batch Cosine Similarity ──
def batch_cosine_similarity(query_vecs: np.ndarray, corpus_vecs: np.ndarray, top_k: int = 10, threshold: float = 0.80):
    """
    query_vecs: (Q, D)  — CRM 客户名
    corpus_vecs: (N, D) — 所有源公司名
    返回: list of (query_idx, corpus_idx, similarity) 超过阈值的候选对
    """
    # L2 normalize
    query_norm = query_vecs / (np.linalg.norm(query_vecs, axis=1, keepdims=True) + 1e-10)
    corpus_norm = corpus_vecs / (np.linalg.norm(corpus_vecs, axis=1, keepdims=True) + 1e-10)
    
    # (Q, D) @ (D, N) → (Q, N)
    sim_matrix = query_norm @ corpus_norm.T
    
    candidates = []
    for qi in range(sim_matrix.shape[0]):
        scores = sim_matrix[qi]
        # 取 top-K
        top_indices = np.argsort(scores)[-top_k:]
        for ci in top_indices:
            if scores[ci] >= threshold:
                candidates.append((qi, int(ci), float(scores[ci])))
    
    return candidates
```

- [ ] **Step 3: rule_score — 编辑距离 + 包含关系 + 简称映射**

```python
def normalize_company_name(name: str) -> str:
    """标准化公司名：去括号、去后缀、去空格"""
    name = re.sub(r'[（()）\s]', '', name)
    name = re.sub(r'(有限公司|股份有限公司|有限责任公司|集团)', '', name)
    name = re.sub(r'(公司|企业|单位)', '', name)
    return name.strip()

def calc_rule_score(name_a: str, name_b: str) -> float:
    """规则相似度 (0~1)"""
    na = normalize_company_name(name_a)
    nb = normalize_company_name(name_b)
    
    # 完全相同
    if na == nb:
        return 1.0
    
    # 包含关系
    if na in nb or nb in na:
        shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
        return min(0.9, len(shorter) / len(longer) + 0.3)
    
    # 编辑距离（Levenshtein）
    max_len = max(len(na), len(nb))
    if max_len == 0:
        return 0.0
    
    # 简化的编辑距离比
    dist = _levenshtein(na, nb)
    similarity = 1.0 - (dist / max_len)
    return max(0.0, similarity)

def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]
```

- [ ] **Step 4: evidence_score — 共享手机号/邮箱**

```python
def calc_evidence_score(name_a: str, name_b: str, mobile_map: dict, email_map: dict) -> float:
    """
    证据分：两个公司名下是否有相同手机号/邮箱的联系人
    mobile_map: {公司名: set(手机号)}
    email_map: {公司名: set(邮箱)}
    """
    mobiles_a = mobile_map.get(name_a, set())
    mobiles_b = mobile_map.get(name_b, set())
    shared_mobiles = mobiles_a & mobiles_b
    
    emails_a = email_map.get(name_a, set())
    emails_b = email_map.get(name_b, set())
    shared_emails = emails_a & emails_b
    
    score = 0.0
    # 共享手机号：每个+0.3，上限0.6
    score += min(len(shared_mobiles) * 0.3, 0.6)
    # 共享邮箱：每个+0.2，上限0.4
    score += min(len(shared_emails) * 0.2, 0.4)
    
    return min(score, 1.0)
```

- [ ] **Step 5: LLM 精判（只对 rule+evidence > 0.5 的候选对）**

```python
def llm_judge(name_a: str, name_b: str, evidence: dict, api_key: str, base_url: str) -> float:
    """
    LLM 判断两个公司名是否同一主体
    返回 0~1 置信分
    """
    prompt = f"""判断以下两个公司名称是否指向同一家公司/机构。
公司A: {name_a}
公司B: {name_b}
辅助证据: 共享手机号{evidence.get('shared_mobiles', 0)}个, 共享邮箱{evidence.get('shared_emails', 0)}个

请只回答一个 0 到 1 之间的数字表示置信度：
1.0 = 确定是同一主体
0.8 = 极大概率同一主体（如简称与全称）
0.5 = 不确定
0.2 = 大概率不是
0.0 = 确定不是同一主体

只输出数字，不要解释。"""
    
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 10,
        },
        timeout=15,
    )
    text = resp.json()["choices"][0]["message"]["content"].strip()
    try:
        return float(re.search(r'[\d.]+', text).group())
    except:
        return 0.5

# ── 三路加权综合分 ──
def calc_match_score(rule: float, evidence: float, llm: float) -> float:
    """加权综合分"""
    return rule * 0.3 + evidence * 0.3 + llm * 0.4

def classify_match(score: float) -> str:
    """分类：自动合并 / 待审核 / 不聚合"""
    if score > 0.85:
        return "auto_merge"
    elif score > 0.6:
        return "pending_review"
    else:
        return "no_merge"
```

- [ ] **Step 6: 主流程 — 全量/增量匹配**

```python
def run_dedup(incremental: bool = False, api_key: str = "", base_url: str = ""):
    """
    执行公司名去重匹配
    incremental=True 时只处理新增的公司名
    """
    import pymysql
    
    # 1. 加载 SQLite 公司名库
    sconn = sqlite3.connect(SQLITE_PATH)
    all_companies = sconn.execute("SELECT id, name, source, is_crm FROM companies").fetchall()
    sconn.close()
    
    crm_names = [c[1] for c in all_companies if c[3] == 1]  # CRM 客户名
    all_names = [c[1] for c in all_companies]
    
    # 去重
    unique_names = list(set(all_names))
    name_to_idx = {n: i for i, n in enumerate(unique_names)}
    crm_indices = [name_to_idx[n] for n in crm_names if n in name_to_idx]
    
    print(f"CRM客户: {len(crm_names)}, 全源unique: {len(unique_names)}")
    
    # 增量过滤：只对新名称做 embedding
    if incremental:
        mconn = pymysql.connect(**DB_MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)
        existing = set(r["candidate_a"] for r in mconn.execute("SELECT candidate_a FROM dws_review_queue").fetchall())
        mconn.close()
        crm_names_to_process = [n for n in crm_names if n not in existing]
        print(f"增量模式: {len(crm_names_to_process)} 个新客户名待处理")
    else:
        crm_names_to_process = crm_names
    
    if not crm_names_to_process:
        print("无新增客户名，跳过")
        return
    
    # 2. Embedding
    print("计算 Embedding...")
    corpus_vecs = get_embeddings(unique_names, api_key, base_url)
    query_vecs = get_embeddings(crm_names_to_process, api_key, base_url)
    
    # 3. Batch cosine similarity
    print("相似度搜索...")
    candidates = batch_cosine_similarity(query_vecs, corpus_vecs, top_k=10, threshold=0.80)
    print(f"候选对: {len(candidates)}")
    
    # 4. 构建手机号/邮箱映射（用于 evidence_score）
    mconn = pymysql.connect(**DB_MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    mobile_map = defaultdict(set)
    email_map = defaultdict(set)
    for row in mconn.execute("SELECT customer_name, mobile, email FROM dws_contact_mapping WHERE mobile IS NOT NULL"):
        mobile_map[row["customer_name"]].add(row["mobile"])
        if row.get("email"):
            email_map[row["customer_name"]].add(row["email"])
    
    # 5. 对每个候选对打分
    review_rows = []
    for qi, ci, emb_sim in candidates:
        name_a = crm_names_to_process[qi]
        name_b = unique_names[ci]
        if name_a == name_b:
            continue  # 跳过自身
        
        rule = calc_rule_score(name_a, name_b)
        evidence = calc_evidence_score(name_a, name_b, mobile_map, email_map)
        
        # 只对 rule + evidence > 0.5 调 LLM
        if rule + evidence > 0.5:
            shared_m = len(mobile_map.get(name_a, set()) & mobile_map.get(name_b, set()))
            shared_e = len(email_map.get(name_a, set()) & email_map.get(name_b, set()))
            llm = llm_judge(name_a, name_b, {"shared_mobiles": shared_m, "shared_emails": shared_e}, api_key, base_url)
        else:
            llm = 0.0
        
        match = calc_match_score(rule, evidence, llm)
        status = classify_match(match)
        
        if status != "no_merge":
            review_rows.append((
                "company_merge", name_a, name_b, match,
                json.dumps({"rule": rule, "evidence": evidence, "llm": llm,
                           "emb_sim": emb_sim, "status": status}, ensure_ascii=False),
                "pending" if status == "pending_review" else "auto_merge",
            ))
    
    # 6. 写入审核队列
    if review_rows:
        cur = mconn.cursor()
        cur.executemany("""
            INSERT INTO dws_review_queue (review_type, candidate_a, candidate_b, match_score, evidence, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, review_rows)
        
        # auto_merge 的直接更新 contact_mapping
        auto = [r for r in review_rows if r[5] == "auto_merge"]
        for _, name_a, name_b, _, _, _ in auto:
            cur.execute("""
                UPDATE dws_contact_mapping SET customer_name = %s WHERE customer_name = %s
            """, (name_a, name_b))
        
        mconn.commit()
    
    mconn.close()
    print(f"完成: {len(review_rows)} 对匹配 (auto: {sum(1 for r in review_rows if r[5]=='auto_merge')}, review: {sum(1 for r in review_rows if r[5]=='pending_review')})")
```

- [ ] **Step 7: 集成到 ETL 流程（增量触发）**

在 `etl_sync.py` 的 `run_etl()` 末尾添加：

```python
# ETL 完成后，增量触发公司名去重
from app.services.company_dedup import run_dedup
from app.config import settings

# 更新 SQLite（检测新公司名）
from data.build_company_db import build_or_update
build_or_update()

# 增量匹配
run_dedup(incremental=True, api_key=settings.llm_api_key, base_url=settings.llm_base_url)
```

- [ ] **Step 8: 手动触发全量匹配 API**

```python
# main.py 中添加
@app.post("/api/admin/dedup/run")
def trigger_dedup(full: bool = False):
    from app.services.company_dedup import run_dedup
    from data.build_company_db import build_or_update
    from app.config import settings
    build_or_update()
    run_dedup(incremental=not full, api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    return {"status": "ok"}
```

- [ ] **Step 9: 验证**

```sql
-- 审核队列
SELECT review_type, candidate_a, candidate_b, match_score, 
       JSON_EXTRACT(evidence, '$.rule') as rule,
       JSON_EXTRACT(evidence, '$.evidence') as evd,
       JSON_EXTRACT(evidence, '$.llm') as llm,
       status
FROM dws_review_queue ORDER BY match_score DESC LIMIT 20;

-- 自动合并统计
SELECT status, COUNT(*) FROM dws_review_queue GROUP BY status;
```

- [ ] **Step 10: Commit**

```bash
git add backend/ data/ && git commit -m "feat: company name dedup with embedding clustering + LLM scoring + incremental"
```

---

## Phase 2: P0 核心功能 (Tasks 5-9)

### Task 5: 客户360列表 — 后端 API

**Files:**
- Create: `backend/app/routers/customer_list.py`
- Create: `backend/app/services/customer_service.py`
- Create: `backend/app/models/schemas.py`

- [ ] **Step 1: 创建 schemas.py — 列表响应模型**

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CustomerListItem(BaseModel):
    id: int
    customer_name: str
    industry: Optional[str] = None
    region: Optional[str] = None
    owner_name: Optional[str] = None
    campaign_tag: str = "企业彩光ICT"
    purchase_stage: Optional[str] = None
    role_coverage: Optional[str] = None
    intent_score: int = 0
    intent_level: Optional[str] = None
    interaction_count_30d: int = 0
    last_interaction_time: Optional[datetime] = None
    last_interaction_channel: Optional[str] = None
    active_opp_count: int = 0
    active_opp_amount: float = 0
    contact_count: int = 0
    is_existing_customer: bool = False

    class Config:
        from_attributes = True

class CustomerListResponse(BaseModel):
    total: int
    items: list[CustomerListItem]
    filters_applied: dict = {}
```

- [ ] **Step 2: 创建 customer_service.py — 列表查询服务**

```python
from sqlalchemy import text
from sqlalchemy.orm import Session

def build_list_query(filters: dict) -> tuple[str, dict]:
    """构建客户列表查询 SQL + 参数"""
    conditions = ["1=1"]
    params = {}
    
    if filters.get("keyword"):
        conditions.append("customer_name LIKE :keyword")
        params["keyword"] = f"%{filters['keyword']}%"
    
    if filters.get("industry"):
        conditions.append("industry = :industry")
        params["industry"] = filters["industry"]
    
    if filters.get("owner"):
        conditions.append("owner_name = :owner")
        params["owner"] = filters["owner"]
    
    if filters.get("stage"):
        conditions.append("purchase_stage = :stage")
        params["stage"] = filters["stage"]
    
    if filters.get("intent_level"):
        conditions.append("intent_level = :intent_level")
        params["intent_level"] = filters["intent_level"]
    
    if filters.get("interaction_min") is not None:
        conditions.append("interaction_count_30d >= :interaction_min")
        params["interaction_min"] = int(filters["interaction_min"])
    
    if filters.get("channel"):
        conditions.append("JSON_CONTAINS(top_channels, JSON_QUOTE(:channel))")
        params["channel"] = filters["channel"]
    
    where = " AND ".join(conditions)
    
    sort_map = {
        "intent": "intent_score DESC",
        "interaction": "interaction_count_30d DESC",
        "last_active": "last_interaction_time DESC",
        "opp_amount": "active_opp_amount DESC",
    }
    order = sort_map.get(filters.get("sort", ""), "intent_score DESC")
    
    page = int(filters.get("page", 1))
    size = int(filters.get("size", 20))
    offset = (page - 1) * size
    
    count_sql = f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where}"
    
    data_sql = f"""
    SELECT * FROM dws_customer_360
    WHERE {where}
    ORDER BY {order}
    LIMIT :limit OFFSET :offset
    """
    params["limit"] = size
    params["offset"] = offset
    
    return count_sql, data_sql, params

def get_customer_list(db: Session, filters: dict) -> dict:
    count_sql, data_sql, params = build_list_query(filters)
    
    total = db.execute(text(count_sql), params).scalar()
    rows = db.execute(text(data_sql), params).mappings().all()
    
    return {
        "total": total,
        "items": [dict(r) for r in rows],
        "filters_applied": {k: v for k, v in filters.items() if v},
    }

def get_filter_options(db: Session) -> dict:
    """获取筛选项的可选值"""
    industries = [r[0] for r in db.execute(text(
        "SELECT DISTINCT industry FROM dws_customer_360 WHERE industry IS NOT NULL"
    )).fetchall()]
    owners = [r[0] for r in db.execute(text(
        "SELECT DISTINCT owner_name FROM dws_customer_360 WHERE owner_name IS NOT NULL ORDER BY owner_name"
    )).fetchall()]
    stages = [r[0] for r in db.execute(text(
        "SELECT DISTINCT purchase_stage FROM dws_customer_360 WHERE purchase_stage IS NOT NULL"
    )).fetchall()]
    return {"industries": industries, "owners": owners, "stages": stages}
```

- [ ] **Step 3: 创建 customer_list.py 路由**

```python
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.customer_service import get_customer_list, get_filter_options
from app.services.export_service import export_customers_excel

router = APIRouter(prefix="/api/customers", tags=["customers"])

@router.get("")
def list_customers(
    keyword: str = Query(None),
    industry: str = Query(None),
    owner: str = Query(None),
    stage: str = Query(None),
    intent_level: str = Query(None),
    interaction_min: int = Query(None),
    channel: str = Query(None),
    sort: str = Query("intent"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    filters = {
        "keyword": keyword, "industry": industry, "owner": owner,
        "stage": stage, "intent_level": intent_level,
        "interaction_min": interaction_min, "channel": channel,
        "sort": sort, "page": page, "size": size,
    }
    return get_customer_list(db, filters)

@router.get("/filter-options")
def filter_options(db: Session = Depends(get_db)):
    return get_filter_options(db)

@router.get("/export")
def export_customers(
    keyword: str = Query(None),
    industry: str = Query(None),
    owner: str = Query(None),
    stage: str = Query(None),
    db: Session = Depends(get_db),
):
    filters = {"keyword": keyword, "industry": industry, "owner": owner, "stage": stage, "page": 1, "size": 10000}
    result = get_customer_list(db, filters)
    buffer = export_customers_excel(result["items"])
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=customers_360.xlsx"},
    )
```

- [ ] **Step 4: 注册路由到 main.py**

```python
from app.routers import customer_list
app.include_router(customer_list.router)
```

- [ ] **Step 5: 创建 export_service.py**

```python
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

EXPORT_COLUMNS = [
    ("customer_name", "客户名称"),
    ("industry", "行业"),
    ("region", "区域"),
    ("owner_name", "负责人"),
    ("campaign_tag", "专项"),
    ("purchase_stage", "采购阶段"),
    ("role_coverage", "关键角色覆盖"),
    ("intent_level", "合作意向"),
    ("interaction_count_30d", "近30天互动"),
    ("last_interaction_time", "最近互动时间"),
    ("last_interaction_channel", "最近互动渠道"),
    ("active_opp_count", "在途商机数"),
    ("active_opp_amount", "在途金额(万元)"),
    ("contact_count", "联系人数"),
    ("is_existing_customer", "老客户"),
]

def export_customers_excel(items: list[dict]) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "客户360"
    
    # 表头
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    for col_idx, (_, header) in enumerate(EXPORT_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    
    # 数据行
    for row_idx, item in enumerate(items, 2):
        for col_idx, (key, _) in enumerate(EXPORT_COLUMNS, 1):
            value = item.get(key, "")
            if key == "is_existing_customer":
                value = "是" if value else "否"
            if key == "last_interaction_time" and value:
                value = str(value)
            ws.cell(row=row_idx, column=col_idx, value=value)
    
    # 列宽
    for col_idx, (_, header) in enumerate(EXPORT_COLUMNS, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(len(header) * 2, 14)
    
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
```

- [ ] **Step 6: 测试 API**

Run: `curl "http://127.0.0.1:8000/api/customers?page=1&size=5"`
Expected: JSON with `total`, `items` array

- [ ] **Step 7: Commit**

```bash
git add backend/ && git commit -m "feat: customer 360 list API with filters and export"
```

---

### Task 6: 客户360列表 — 前端页面

**Files:**
- Create: `frontend/src/views/CustomerList.vue`
- Create: `frontend/src/components/customer/FilterBar.vue`
- Create: `frontend/src/components/customer/CustomerTable.vue`
- Create: `frontend/src/components/customer/ExportButton.vue`
- Create: `frontend/src/stores/customer.js`

- [ ] **Step 1: 创建 customer store**

```javascript
// stores/customer.js
import { defineStore } from 'pinia'
import { customerApi, exportApi } from '../api'

export const useCustomerStore = defineStore('customer', {
  state: () => ({
    items: [],
    total: 0,
    loading: false,
    filters: {
      keyword: '',
      industry: '',
      owner: '',
      stage: '',
      intent_level: '',
      interaction_min: null,
      channel: '',
      sort: 'intent',
      page: 1,
      size: 20,
    },
    filterOptions: { industries: [], owners: [], stages: [] },
  }),
  actions: {
    async fetchList() {
      this.loading = true
      try {
        const { data } = await customerApi.getList(this.filters)
        this.items = data.items
        this.total = data.total
      } finally {
        this.loading = false
      }
    },
    async fetchFilterOptions() {
      const { data } = await customerApi.getFilterOptions()
      this.filterOptions = data
    },
    setFilter(key, value) {
      this.filters[key] = value
      this.filters.page = 1
      this.fetchList()
    },
    setPage(page) {
      this.filters.page = page
      this.fetchList()
    },
    async exportExcel() {
      const response = await exportApi.customers(this.filters)
      const url = URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'customers_360.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    },
  },
})
```

- [ ] **Step 2: 创建 FilterBar.vue**

```html
<template>
  <div class="bg-[var(--panel)] border border-[var(--line)] rounded-2xl p-4 mb-4">
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
      <div class="flex flex-col gap-1">
        <label class="text-xs text-[var(--muted)]">专项</label>
        <select class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm" disabled>
          <option>企业彩光ICT</option>
        </select>
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-[var(--muted)]">客户关键词</label>
        <input v-model="local.keyword" @keyup.enter="apply" type="text" placeholder="模糊搜索客户名"
          class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm" />
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-[var(--muted)]">行业</label>
        <select v-model="local.industry" class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm">
          <option value="">全部</option>
          <option v-for="i in store.filterOptions.industries" :key="i" :value="i">{{ i }}</option>
        </select>
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-[var(--muted)]">负责人</label>
        <select v-model="local.owner" class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm">
          <option value="">全部</option>
          <option v-for="o in store.filterOptions.owners" :key="o" :value="o">{{ o }}</option>
        </select>
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-[var(--muted)]">互动次数 ≥</label>
        <input v-model.number="local.interaction_min" type="number" min="0" placeholder="0"
          class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm" />
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-[var(--muted)]">互动方式</label>
        <select v-model="local.channel" class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm">
          <option value="">全部</option>
          <option value="官网">官网</option>
          <option value="直播">直播</option>
          <option value="邮件">邮件</option>
        </select>
      </div>
      <div class="flex items-end">
        <button @click="apply" class="w-full bg-[var(--brand)] text-white rounded-xl px-4 py-2 text-sm font-bold hover:opacity-90 transition">
          应用
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { useCustomerStore } from '../../stores/customer'

const store = useCustomerStore()
const local = reactive({ ...store.filters })

function apply() {
  Object.keys(local).forEach(key => {
    store.filters[key] = local[key]
  })
  store.filters.page = 1
  store.fetchList()
}
</script>
```

- [ ] **Step 3: 创建 CustomerTable.vue**

```html
<template>
  <div class="bg-[var(--panel)] border border-[var(--line)] rounded-2xl overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-[var(--line)] bg-white/5">
            <th class="px-4 py-3 text-left font-semibold text-[var(--muted)]">客户名称</th>
            <th class="px-4 py-3 text-left font-semibold text-[var(--muted)]">专项/行业</th>
            <th class="px-4 py-3 text-center font-semibold text-[var(--muted)]">采购阶段</th>
            <th class="px-4 py-3 text-center font-semibold text-[var(--muted)]">关键角色覆盖</th>
            <th class="px-4 py-3 text-center font-semibold text-[var(--muted)]">合作意向</th>
            <th class="px-4 py-3 text-left font-semibold text-[var(--muted)]">最近互动</th>
            <th class="px-4 py-3 text-center font-semibold text-[var(--muted)]">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.id"
            class="border-b border-[var(--line)]/50 hover:bg-white/5 transition cursor-pointer"
            @click="$router.push(`/customers/${item.id}`)">
            <td class="px-4 py-3 font-medium">{{ item.customer_name }}</td>
            <td class="px-4 py-3">
              <span class="text-xs px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-300">{{ item.campaign_tag }}</span>
              <span class="ml-2 text-xs text-[var(--muted)]">{{ item.industry || '-' }}</span>
            </td>
            <td class="px-4 py-3 text-center">
              <span class="text-xs px-2 py-0.5 rounded-full"
                :class="stageClass(item.purchase_stage)">{{ item.purchase_stage || '未知' }}</span>
            </td>
            <td class="px-4 py-3 text-center font-mono">{{ item.role_coverage || '0/4' }}</td>
            <td class="px-4 py-3 text-center">
              <span class="text-xs px-2 py-0.5 rounded-full" :class="intentClass(item.intent_level)">
                {{ item.intent_level || '低' }} ({{ item.intent_score }})
              </span>
            </td>
            <td class="px-4 py-3 text-xs text-[var(--muted)]">
              <div>{{ formatDate(item.last_interaction_time) }}</div>
              <div class="text-[10px]">{{ item.last_interaction_channel || '-' }}</div>
            </td>
            <td class="px-4 py-3 text-center">
              <button @click.stop="$router.push(`/customers/${item.id}`)"
                class="text-xs text-[var(--brand)] hover:underline">打开</button>
            </td>
          </tr>
          <tr v-if="!store.items.length && !store.loading">
            <td colspan="7" class="px-4 py-12 text-center text-[var(--muted)]">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>
    <!-- 分页 -->
    <div class="flex items-center justify-between px-4 py-3 border-t border-[var(--line)]">
      <span class="text-xs text-[var(--muted)]">共 {{ store.total }} 条</span>
      <div class="flex gap-1">
        <button v-for="p in totalPages" :key="p" @click="store.setPage(p)"
          class="w-8 h-8 rounded-lg text-xs transition"
          :class="p === store.filters.page ? 'bg-[var(--brand)] text-white' : 'bg-white/5 text-[var(--muted)] hover:bg-white/10'">
          {{ p }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useCustomerStore } from '../../stores/customer'

const store = useCustomerStore()

const totalPages = computed(() => {
  const pages = Math.ceil(store.total / store.filters.size)
  return Math.min(pages, 10) // 最多显示10页
})

function stageClass(stage) {
  const map = {
    '问题识别': 'bg-yellow-500/15 text-yellow-300',
    '解决方案探索': 'bg-blue-500/15 text-blue-300',
    '需求构建': 'bg-green-500/15 text-green-300',
    '已完成': 'bg-emerald-500/15 text-emerald-300',
  }
  return map[stage] || 'bg-gray-500/15 text-gray-400'
}

function intentClass(level) {
  return {
    '高': 'bg-green-500/15 text-green-300',
    '中': 'bg-yellow-500/15 text-yellow-300',
    '低': 'bg-gray-500/15 text-gray-400',
  }[level] || 'bg-gray-500/15 text-gray-400'
}

function formatDate(dt) {
  if (!dt) return '暂无互动'
  return new Date(dt).toLocaleDateString('zh-CN')
}
</script>
```

- [ ] **Step 4: 创建 CustomerList.vue 页面**

```html
<template>
  <div>
    <FilterBar />
    <div class="flex items-center justify-between mb-3">
      <span class="text-sm text-[var(--muted)]">
        共 <b class="text-white">{{ store.total }}</b> 个客户
      </span>
      <div class="flex gap-2">
        <button @click="store.exportExcel()"
          class="px-3 py-1.5 text-xs rounded-lg border border-[var(--line)] bg-white/5 hover:bg-white/10 transition">
          📥 导出筛选结果
        </button>
      </div>
    </div>
    <div v-if="store.loading" class="text-center py-12 text-[var(--muted)]">加载中...</div>
    <CustomerTable v-else />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useCustomerStore } from '../stores/customer'
import FilterBar from '../components/customer/FilterBar.vue'
import CustomerTable from '../components/customer/CustomerTable.vue'

const store = useCustomerStore()
onMounted(() => {
  store.fetchFilterOptions()
  store.fetchList()
})
</script>
```

- [ ] **Step 5: 验证**

Run: 启动前后端，浏览器访问 http://localhost:3000/customers
Expected: 显示客户列表，支持筛选和分页

- [ ] **Step 6: Commit**

```bash
git add frontend/ && git commit -m "feat: customer 360 list page with filters, table, export"
```

---

### Task 7: 客户360详情 — 后端 API

**Files:**
- Create: `backend/app/routers/customer_detail.py`
- Create: `backend/app/services/interaction_service.py`
- Create: `backend/app/services/opportunity_service.py`
- Create: `backend/app/services/scoring_service.py`

- [ ] **Step 1: 创建 customer_detail.py 路由**

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.services.interaction_service import get_customer_interactions, get_contact_interactions
from app.services.opportunity_service import get_customer_opportunities
from app.services.scoring_service import get_ai_insight, get_priority_contact

router = APIRouter(prefix="/api/customers", tags=["customer-detail"])

@router.get("/{customer_id}")
def get_customer_detail(customer_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM dws_customer_360 WHERE id = :id"), {"id": customer_id}).mappings().first()
    if not row:
        raise HTTPException(404, "客户不存在")
    return dict(row)

@router.get("/{customer_id}/contacts")
def get_contacts(customer_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text(
        "SELECT * FROM dws_contact_360 WHERE customer_id = :cid ORDER BY interaction_count DESC"
    ), {"cid": customer_id}).mappings().all()
    return [dict(r) for r in rows]

@router.get("/{customer_id}/interactions")
def get_interactions(
    customer_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    customer = db.execute(text("SELECT customer_name FROM dws_customer_360 WHERE id = :id"), {"id": customer_id}).scalar()
    if not customer:
        raise HTTPException(404, "客户不存在")
    return get_customer_interactions(db, customer, limit)

@router.get("/{customer_id}/opportunities")
def get_opportunities(customer_id: int, db: Session = Depends(get_db)):
    customer = db.execute(text("SELECT customer_name FROM dws_customer_360 WHERE id = :id"), {"id": customer_id}).scalar()
    if not customer:
        raise HTTPException(404, "客户不存在")
    return get_customer_opportunities(db, customer)

@router.get("/{customer_id}/ai-insight")
def get_insight(customer_id: int, db: Session = Depends(get_db)):
    detail = db.execute(text("SELECT * FROM dws_customer_360 WHERE id = :id"), {"id": customer_id}).mappings().first()
    if not detail:
        raise HTTPException(404, "客户不存在")
    contacts = db.execute(text(
        "SELECT * FROM dws_contact_360 WHERE customer_id = :cid ORDER BY interaction_count DESC LIMIT 10"
    ), {"cid": customer_id}).mappings().all()
    return get_ai_insight(dict(detail), [dict(c) for c in contacts])

@router.get("/{customer_id}/priority-contact")
def get_priority(customer_id: int, db: Session = Depends(get_db)):
    contacts = db.execute(text(
        "SELECT * FROM dws_contact_360 WHERE customer_id = :cid ORDER BY interaction_count DESC"
    ), {"cid": customer_id}).mappings().all()
    return get_priority_contact([dict(c) for c in contacts])
```

- [ ] **Step 2: 创建 interaction_service.py（使用预聚合表）**

```python
from sqlalchemy import text
from sqlalchemy.orm import Session

def get_customer_interactions(db: Session, customer_name: str, limit: int = 50) -> list:
    """从预聚合的 dws_interaction_detail 表查询客户互动
    数据来源已由 init_data.py 三层拼接完成，无需再查 ODS 大表"""
    rows = db.execute(text("""
        SELECT source_table as source, customer_name as company,
               contact_name as who, channel,
               behavior_type, content, event_time, is_high_value
        FROM dws_interaction_detail
        WHERE customer_name = :name AND event_time IS NOT NULL
        ORDER BY event_time DESC
        LIMIT :limit
    """), {"name": customer_name, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]

def get_contact_interactions(db: Session, mobile: str, limit: int = 20) -> list:
    """按手机号查询单个联系人的互动"""
    if not mobile:
        return []
    rows = db.execute(text("""
        SELECT source_table as source, channel, behavior_type,
               content, event_time, is_high_value
        FROM dws_interaction_detail
        WHERE mobile = :mobile AND event_time IS NOT NULL
        ORDER BY event_time DESC
        LIMIT :limit
    """), {"mobile": mobile, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]
```

- [ ] **Step 3: 创建 opportunity_service.py**

```python
from sqlalchemy import text
from sqlalchemy.orm import Session

def get_customer_opportunities(db: Session, customer_name: str) -> list:
    rows = db.execute(text("""
        SELECT opp_name, opp_code, is_funnel, forecast_type,
               amount_10k, win_rate, actual_order_amount_10k,
               is_cancel_lost, owner_name, customer_stage,
               product_category, create_date, expect_order_date
        FROM ods_crm_opportunity_day
        WHERE customer_name = :name
        ORDER BY create_date DESC
    """), {"name": customer_name}).mappings().all()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: 创建 scoring_service.py**

```python
import json

ROLE_WEIGHTS = {"拍板者": 90, "决策者": 75, "评估者": 55, "采购推动者": 45, "普通": 25}
STAGE_WEIGHTS = {"需求构建": 10, "解决方案探索": 6, "问题识别": 3}

def get_ai_insight(customer: dict, contacts: list) -> dict:
    """基于规则生成 AI 洞察（生产环境替换为 LLM 调用）"""
    conclusions = []
    
    # 业务结论
    stage = customer.get("purchase_stage", "未知")
    intent = customer.get("intent_level", "低")
    opp_count = customer.get("active_opp_count", 0)
    opp_amount = customer.get("active_opp_amount", 0)
    
    conclusions.append(f"客户当前采购阶段为「{stage}」，合作意向{intent}，在途商机{opp_count}个(金额{opp_amount}万元)。")
    
    if customer.get("is_existing_customer"):
        conclusions.append(f"该客户为老客户，历史成交金额{customer.get('won_amount', 0)}万元。")
    
    # 联系人洞察
    contact_insights = []
    for c in contacts[:3]:
        role = c.get("role_category", "普通")
        count = c.get("interaction_count", 0)
        contact_insights.append(f"{c.get('contact_name', '未知')}({role})，互动{count}次")
    
    # 角色覆盖分析
    coverage = customer.get("role_coverage", "0/4")
    covered = int(coverage.split("/")[0]) if "/" in coverage else 0
    if covered < 4:
        missing = 4 - covered
        conclusions.append(f"关键角色覆盖{coverage}，尚缺{missing}类角色需触达。")
    
    return {
        "business_conclusion": conclusions,
        "contact_insights": contact_insights,
        "evidence": {
            "purchase_stage": stage,
            "intent_level": intent,
            "role_coverage": coverage,
            "active_opps": opp_count,
        },
    }

def get_priority_contact(contacts: list) -> dict:
    """计算优先推进联系人"""
    if not contacts:
        return {"recommended": None, "candidates": []}
    
    scored = []
    for c in contacts:
        role = c.get("role_category", "普通")
        score = ROLE_WEIGHTS.get(role, 25)
        score += min(c.get("interaction_count_30d", 0) * 2, 30)
        # 高价值行为额外加分（简化处理）
        if c.get("interaction_count", 0) > 5:
            score += 8
        scored.append({**c, "priority_score": score})
    
    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    return {
        "recommended": scored[0] if scored else None,
        "candidates": scored[:3],
    }
```

- [ ] **Step 5: 注册路由**

```python
from app.routers import customer_detail
app.include_router(customer_detail.router)
```

- [ ] **Step 6: 测试**

Run: `curl "http://127.0.0.1:8000/api/customers/1"`
Run: `curl "http://127.0.0.1:8000/api/customers/1/contacts"`
Run: `curl "http://127.0.0.1:8000/api/customers/1/interactions"`
Run: `curl "http://127.0.0.1:8000/api/customers/1/ai-insight"`

- [ ] **Step 7: Commit**

```bash
git add backend/ && git commit -m "feat: customer detail API with contacts, interactions, insights"
```

---

### Task 8: 客户360详情 — 前端页面（概览 TAB）

**Files:**
- Create: `frontend/src/views/CustomerDetail.vue`
- Create: `frontend/src/components/detail/KpiCards.vue`
- Create: `frontend/src/components/detail/CustomerProfile.vue`
- Create: `frontend/src/components/detail/BusinessTags.vue`
- Create: `frontend/src/components/detail/FollowupStatus.vue`
- Create: `frontend/src/components/detail/OpportunityBudget.vue`
- Create: `frontend/src/components/detail/BehaviorTimeline.vue`
- Create: `frontend/src/components/detail/AiInsight.vue`

- [ ] **Step 1: 创建 CustomerDetail.vue（含 TAB 切换）**

```html
<template>
  <div>
    <!-- 公共头部 -->
    <div class="bg-[var(--panel)] border border-[var(--line)] rounded-2xl p-5 mb-4">
      <div class="flex items-start justify-between">
        <div>
          <button @click="$router.back()" class="text-xs text-[var(--muted)] hover:text-white mb-2">← 返回列表</button>
          <h2 class="text-xl font-bold">{{ detail.customer_name }}</h2>
          <div class="flex gap-3 mt-2 text-sm text-[var(--muted)]">
            <span>专项: {{ detail.campaign_tag }}</span>
            <span>行业: {{ detail.industry || '-' }}</span>
            <span>区域: {{ detail.region || '-' }}</span>
            <span>负责人: {{ detail.owner_name || '未分配' }}</span>
            <span>最近互动: {{ formatDate(detail.last_interaction_time) }}</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- TAB 导航 -->
    <div class="flex gap-1 mb-4 bg-[var(--panel)] border border-[var(--line)] rounded-xl p-1 w-fit">
      <button v-for="tab in tabs" :key="tab.key" @click="activeTab = tab.key"
        class="px-4 py-2 rounded-lg text-sm transition"
        :class="activeTab === tab.key ? 'bg-[var(--brand)] text-white font-bold' : 'text-[var(--muted)] hover:bg-white/5'">
        {{ tab.label }}
      </button>
    </div>
    
    <!-- TAB 内容 -->
    <div v-if="loading" class="text-center py-12 text-[var(--muted)]">加载中...</div>
    <template v-else>
      <OverviewTab v-if="activeTab === 'overview'" :detail="detail" :interactions="interactions" :insight="insight" />
      <ContactsTab v-else-if="activeTab === 'contacts'" :customer-id="customerId" />
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { customerApi } from '../api'
import OverviewTab from '../components/detail/OverviewTab.vue'
import ContactsTab from '../components/detail/ContactsTab.vue'

const route = useRoute()
const customerId = computed(() => route.params.id)
const activeTab = ref('overview')
const loading = ref(true)
const detail = ref({})
const interactions = ref([])
const insight = ref({})

const tabs = [
  { key: 'overview', label: '概览' },
  { key: 'contacts', label: '联系人' },
]

function formatDate(dt) {
  if (!dt) return '暂无互动'
  return new Date(dt).toLocaleDateString('zh-CN')
}

onMounted(async () => {
  try {
    const [detailRes, interRes, insightRes] = await Promise.all([
      customerApi.getDetail(customerId.value),
      customerApi.getInteractions(customerId.value),
      customerApi.getAiInsight(customerId.value),
    ])
    detail.value = detailRes.data
    interactions.value = interRes.data
    insight.value = insightRes.data
  } finally {
    loading.value = false
  }
})
</script>
```

- [ ] **Step 2: 创建 OverviewTab.vue（组合所有概览模块）**

```html
<template>
  <div class="space-y-4">
    <!-- 顶部 KPI -->
    <KpiCards :detail="detail" />
    
    <div class="grid grid-cols-2 gap-4">
      <!-- 客户档案 -->
      <CustomerProfile :detail="detail" />
      <!-- 业务标签 -->
      <BusinessTags :detail="detail" />
    </div>
    
    <div class="grid grid-cols-2 gap-4">
      <!-- 跟进状态 -->
      <FollowupStatus :detail="detail" />
      <!-- 商机&预算 -->
      <OpportunityBudget :detail="detail" />
    </div>
    
    <!-- 客户行为卡片 -->
    <BehaviorTimeline :interactions="interactions" />
    
    <!-- AI 洞察 -->
    <AiInsight :insight="insight" />
  </div>
</template>

<script setup>
import KpiCards from './KpiCards.vue'
import CustomerProfile from './CustomerProfile.vue'
import BusinessTags from './BusinessTags.vue'
import FollowupStatus from './FollowupStatus.vue'
import OpportunityBudget from './OpportunityBudget.vue'
import BehaviorTimeline from './BehaviorTimeline.vue'
import AiInsight from './AiInsight.vue'

defineProps({ detail: Object, interactions: Array, insight: Object })
</script>
```

- [ ] **Step 3: 创建 KpiCards.vue**

```html
<template>
  <div class="grid grid-cols-5 gap-3">
    <div v-for="kpi in kpis" :key="kpi.label"
      class="bg-[var(--panel)] border border-[var(--line)] rounded-xl p-4">
      <div class="text-xs text-[var(--muted)] mb-1">{{ kpi.label }}</div>
      <div class="text-lg font-bold">{{ kpi.value }}</div>
      <div v-if="kpi.sub" class="text-xs text-[var(--muted)] mt-1">{{ kpi.sub }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ detail: Object })

const kpis = computed(() => [
  { label: '合作意向', value: props.detail.intent_level || '低', sub: `得分: ${props.detail.intent_score || 0}` },
  { label: '近30天互动', value: `${props.detail.interaction_count_30d || 0} 次`, sub: '' },
  { label: '采购阶段', value: props.detail.purchase_stage || '未知', sub: props.detail.forecast_type || '' },
  { label: '关键角色覆盖', value: props.detail.role_coverage || '0/4', sub: '' },
  { label: '在途商机', value: `${props.detail.active_opp_count || 0} 个`, sub: `${props.detail.active_opp_amount || 0} 万元` },
])
</script>
```

- [ ] **Step 4: 创建 CustomerProfile.vue / BusinessTags.vue / FollowupStatus.vue / OpportunityBudget.vue**

每个组件接收 `detail` prop，渲染对应的字段卡片。样式统一使用暗色面板 + 字段键值对。

- [ ] **Step 5: 创建 BehaviorTimeline.vue**

```html
<template>
  <div class="bg-[var(--panel)] border border-[var(--line)] rounded-2xl p-5">
    <h3 class="text-sm font-bold mb-4">客户行为卡片</h3>
    <div class="relative pl-4 space-y-3">
      <div class="absolute left-[7px] top-1 bottom-1 w-px bg-gradient-to-b from-blue-500/50 to-emerald-500/20"></div>
      <div v-for="(item, i) in interactions.slice(0, 20)" :key="i" class="relative">
        <div class="absolute -left-[11px] top-3 w-2.5 h-2.5 rounded-full bg-gradient-to-b from-blue-400 to-emerald-400 shadow-lg shadow-blue-500/20"></div>
        <div class="border border-[var(--line)] rounded-xl p-3 bg-white/[.03]">
          <div class="flex justify-between items-center">
            <span class="text-xs font-bold">{{ item.source }} · {{ item.channel }}</span>
            <span class="text-xs text-[var(--muted)]">{{ formatDate(item.event_time) }}</span>
          </div>
          <div class="text-xs text-[var(--muted)] mt-1">
            <span class="text-white/80">{{ item.who || '未识别联系人' }}</span> — {{ item.content || '无互动内容' }}
          </div>
        </div>
      </div>
      <div v-if="!interactions.length" class="text-sm text-[var(--muted)] py-4">暂无互动记录</div>
    </div>
  </div>
</template>

<script setup>
defineProps({ interactions: Array })
function formatDate(dt) {
  if (!dt) return '-'
  return new Date(dt).toLocaleString('zh-CN')
}
</script>
```

- [ ] **Step 6: 创建 AiInsight.vue**

```html
<template>
  <div class="bg-[var(--panel)] border border-[var(--line)] rounded-2xl p-5">
    <h3 class="text-sm font-bold mb-4 flex items-center gap-2">
      <span class="w-2 h-2 rounded-full bg-[var(--brand)]"></span>
      AI 洞察
    </h3>
    <div v-if="insight.business_conclusion" class="space-y-2 mb-4">
      <div class="text-xs text-[var(--muted)] font-bold">业务结论</div>
      <p v-for="(line, i) in insight.business_conclusion" :key="i" class="text-sm leading-relaxed">{{ line }}</p>
    </div>
    <div v-if="insight.contact_insights?.length" class="space-y-2 mb-4">
      <div class="text-xs text-[var(--muted)] font-bold">联系人 Top3</div>
      <p v-for="(line, i) in insight.contact_insights" :key="i" class="text-sm text-[var(--muted)]">{{ line }}</p>
    </div>
    <div v-if="insight.evidence" class="mt-4 pt-3 border-t border-[var(--line)]/50">
      <div class="text-xs text-[var(--muted)] font-bold mb-2">证据链</div>
      <div class="flex flex-wrap gap-3 text-xs">
        <span v-for="(val, key) in insight.evidence" :key="key"
          class="px-2 py-1 rounded-lg bg-white/5 border border-[var(--line)]/50">
          <span class="text-[var(--muted)]">{{ key }}:</span> <span class="font-bold">{{ val }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ insight: Object })
</script>
```

- [ ] **Step 7: 验证**

点击列表中的客户 → 详情页正确展示概览 TAB 各模块

- [ ] **Step 8: Commit**

```bash
git add frontend/ && git commit -m "feat: customer detail overview tab with KPIs, timeline, AI insight"
```

---

### Task 9: 客户360详情 — 联系人 TAB

**Files:**
- Create: `frontend/src/components/detail/ContactsTab.vue`
- Create: `frontend/src/components/detail/ContactCard.vue`
- Create: `frontend/src/components/detail/AiPriorityContact.vue`

- [ ] **Step 1: 创建 ContactsTab.vue**

```html
<template>
  <div class="space-y-4">
    <!-- AI 优先推进对象 -->
    <AiPriorityContact v-if="priority.recommended" :priority="priority" />
    
    <!-- 筛选栏 -->
    <div class="flex gap-3 items-center">
      <input v-model="search" type="text" placeholder="搜索联系人"
        class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm flex-1" />
      <select v-model="roleFilter" class="bg-white/5 border border-[var(--line)] rounded-xl px-3 py-2 text-sm">
        <option value="">全部角色</option>
        <option value="拍板者">拍板者</option>
        <option value="决策者">决策者</option>
        <option value="评估者">评估者</option>
        <option value="采购推动者">采购推动者</option>
      </select>
    </div>
    
    <!-- 联系人卡片列表 -->
    <div class="grid grid-cols-2 gap-3">
      <ContactCard v-for="c in filteredContacts" :key="c.id" :contact="c" />
    </div>
    <div v-if="!filteredContacts.length" class="text-center py-8 text-[var(--muted)]">暂无联系人</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { customerApi } from '../../api'
import ContactCard from './ContactCard.vue'
import AiPriorityContact from './AiPriorityContact.vue'

const props = defineProps({ customerId: String })
const contacts = ref([])
const priority = ref({})
const search = ref('')
const roleFilter = ref('')

const filteredContacts = computed(() => {
  return contacts.value.filter(c => {
    if (search.value && !c.contact_name?.includes(search.value)) return false
    if (roleFilter.value && c.role_category !== roleFilter.value) return false
    return true
  })
})

onMounted(async () => {
  const [contactsRes, priorityRes] = await Promise.all([
    customerApi.getContacts(props.customerId),
    customerApi.getPriorityContact(props.customerId),
  ])
  contacts.value = contactsRes.data
  priority.value = priorityRes.data
})
</script>
```

- [ ] **Step 2: 创建 ContactCard.vue**

```html
<template>
  <div class="bg-[var(--panel)] border border-[var(--line)] rounded-xl p-4 hover:border-[var(--brand)]/30 transition">
    <div class="flex justify-between items-start mb-3">
      <div>
        <div class="font-bold text-sm">{{ contact.contact_name || '未命名联系人' }}</div>
        <div class="text-xs text-[var(--muted)] mt-1">
          {{ contact.mobile || '-' }} · {{ contact.email || '-' }}
        </div>
      </div>
      <span v-if="contact.role_category" class="text-xs px-2 py-0.5 rounded-full"
        :class="roleClass">{{ contact.role_category }}</span>
    </div>
    <div class="grid grid-cols-3 gap-2 text-center border-t border-[var(--line)]/50 pt-3">
      <div>
        <div class="text-lg font-bold">{{ contact.interaction_count || 0 }}</div>
        <div class="text-[10px] text-[var(--muted)]">总互动</div>
      </div>
      <div>
        <div class="text-lg font-bold">{{ contact.interaction_count_30d || 0 }}</div>
        <div class="text-[10px] text-[var(--muted)]">近30天</div>
      </div>
      <div>
        <div class="text-lg font-bold">{{ contact.activity_level || '-' }}</div>
        <div class="text-[10px] text-[var(--muted)]">活跃度</div>
      </div>
    </div>
    <div v-if="contact.department || contact.position" class="text-xs text-[var(--muted)] mt-2">
      {{ contact.department }} · {{ contact.position }}
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ contact: Object })
const roleClass = computed(() => {
  const map = {
    '拍板者': 'bg-red-500/15 text-red-300',
    '决策者': 'bg-orange-500/15 text-orange-300',
    '评估者': 'bg-blue-500/15 text-blue-300',
    '采购推动者': 'bg-green-500/15 text-green-300',
  }
  return map[props.contact.role_category] || 'bg-gray-500/15 text-gray-400'
})
</script>
```

- [ ] **Step 3: 创建 AiPriorityContact.vue**

```html
<template>
  <div class="bg-gradient-to-r from-blue-500/10 to-emerald-500/5 border border-blue-500/20 rounded-2xl p-5">
    <h3 class="text-sm font-bold flex items-center gap-2 mb-3">
      <span class="w-2 h-2 rounded-full bg-[var(--brand)]"></span>
      AI 优先推进对象
    </h3>
    <div v-if="priority.recommended" class="flex items-center gap-4">
      <div class="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center text-lg font-bold">
        {{ priority.recommended.contact_name?.charAt(0) || '?' }}
      </div>
      <div>
        <div class="font-bold">{{ priority.recommended.contact_name }}</div>
        <div class="text-xs text-[var(--muted)]">
          {{ priority.recommended.role_category }} · 互动 {{ priority.recommended.interaction_count }} 次 ·
          优先分 {{ priority.recommended.priority_score }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({ priority: Object })
</script>
```

- [ ] **Step 4: 验证联系人 TAB**

- [ ] **Step 5: Commit**

```bash
git add frontend/ && git commit -m "feat: customer detail contacts tab with AI priority"
```

---

## Phase 3: P1 功能 (Tasks 10-13)

### Task 10: AI 对话 (NL2SQL + 数据导出)

**Files:**
- Create: `backend/app/routers/ai_chat.py`
- Create: `backend/app/services/ai_service.py`
- Create: `frontend/src/views/AiChat.vue`
- Create: `frontend/src/components/ai/ChatThread.vue`
- Create: `frontend/src/components/ai/EntityChips.vue`
- Create: `frontend/src/components/ai/QueryResultTable.vue`

- [ ] **Step 1: 创建 ai_service.py — 实体解析 + NL2SQL**

```python
import re
import json
from sqlalchemy import text
from sqlalchemy.orm import Session

# 实体抽取规则
ENTITY_PATTERNS = {
    "industry": ["医疗", "企业", "高教职教", "普教", "政府", "运营商", "交通", "金融", "电力能源", "公共安全"],
    "region": ["广东", "北京", "上海", "江苏", "浙江", "山东", "四川", "湖北", "湖南", "河南", "福建"],
    "stage": ["问题识别", "解决方案探索", "需求构建"],
    "intent": ["高", "中", "低"],
    "channel": ["官网", "直播", "邮件"],
}

def parse_query(text: str) -> dict:
    """从自然语言抽取实体"""
    entities = {}
    
    # 行业
    for v in ENTITY_PATTERNS["industry"]:
        if v in text:
            entities.setdefault("industry", []).append(v)
    
    # 区域
    for v in ENTITY_PATTERNS["region"]:
        if v in text:
            entities.setdefault("region", []).append(v)
    
    # 阶段
    for v in ENTITY_PATTERNS["stage"]:
        if v in text:
            entities["stage"] = v
    
    # 互动次数阈值
    match = re.search(r'互动[次超过]*(\d+)', text)
    if match:
        entities["interaction_min"] = int(match.group(1))
    
    # 意向
    for v in ENTITY_PATTERNS["intent"]:
        if f"意向{v}" in text or f"合作意向{v}" in text:
            entities["intent_level"] = v
    
    # 关键词
    match = re.search(r'[包含搜索有关]?(.+?)的?客户', text)
    if match and len(match.group(1)) <= 20:
        entities["keyword"] = match.group(1)
    
    # 有商机
    if "有商机" in text or "在途商机" in text:
        entities["has_opportunity"] = True
    
    return entities

def entities_to_sql(entities: dict, db: Session) -> tuple[list, int]:
    """将实体转换为 SQL 查询并执行"""
    conditions = ["1=1"]
    params = {}
    
    if entities.get("industry"):
        placeholders = [f":ind_{i}" for i in range(len(entities["industry"]))]
        conditions.append(f"industry IN ({','.join(placeholders)})")
        for i, v in enumerate(entities["industry"]):
            params[f"ind_{i}"] = v
    
    if entities.get("region"):
        placeholders = [f":reg_{i}" for i in range(len(entities["region"]))]
        conditions.append(f"region IN ({','.join(placeholders)})")
        for i, v in enumerate(entities["region"]):
            params[f"reg_{i}"] = v
    
    if entities.get("stage"):
        conditions.append("purchase_stage = :stage")
        params["stage"] = entities["stage"]
    
    if entities.get("intent_level"):
        conditions.append("intent_level = :intent")
        params["intent"] = entities["intent_level"]
    
    if entities.get("interaction_min"):
        conditions.append("interaction_count_30d >= :imin")
        params["imin"] = entities["interaction_min"]
    
    if entities.get("keyword"):
        conditions.append("customer_name LIKE :kw")
        params["kw"] = f"%{entities['keyword']}%"
    
    if entities.get("has_opportunity"):
        conditions.append("active_opp_count > 0")
    
    where = " AND ".join(conditions)
    
    count = db.execute(text(f"SELECT COUNT(*) FROM dws_customer_360 WHERE {where}"), params).scalar()
    rows = db.execute(text(
        f"SELECT * FROM dws_customer_360 WHERE {where} ORDER BY intent_score DESC LIMIT 100"
    ), params).mappings().all()
    
    return [dict(r) for r in rows], count

def generate_response(entities: dict, results: list, total: int) -> str:
    """生成 AI 回复文本"""
    if not results:
        return f"未找到符合条件的客户。已识别实体: {json.dumps(entities, ensure_ascii=False)}"
    
    lines = [f"找到 {total} 个符合条件的客户：\n"]
    for r in results[:5]:
        lines.append(f"• {r['customer_name']} — {r.get('industry', '-')} · {r.get('purchase_stage', '未知')} · 意向{r.get('intent_level', '低')}")
    if total > 5:
        lines.append(f"\n...还有 {total - 5} 个客户，可在下方列表查看完整结果。")
    return "\n".join(lines)
```

- [ ] **Step 2: 创建 ai_chat.py 路由**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.ai_service import parse_query, entities_to_sql, generate_response
from app.services.export_service import export_customers_excel
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])

class ChatRequest(BaseModel):
    text: str

class ParseRequest(BaseModel):
    text: str

@router.post("/parse")
def parse(req: ParseRequest):
    return {"entities": parse_query(req.text)}

@router.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    entities = parse_query(req.text)
    results, total = entities_to_sql(entities, db)
    response_text = generate_response(entities, results, total)
    return {
        "entities": entities,
        "response": response_text,
        "results": results,
        "total": total,
    }

@router.post("/chat/export")
def chat_export(req: ChatRequest, db: Session = Depends(get_db)):
    entities = parse_query(req.text)
    results, _ = entities_to_sql(entities, db)
    buffer = export_customers_excel(results)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ai_query_results.xlsx"},
    )
```

- [ ] **Step 3: 创建 AiChat.vue 前端页面**

参考原型中 AI 查询模块：输入框 + 实体 chips + 客户列表 + 导出按钮。

- [ ] **Step 4: 创建 ChatThread.vue / EntityChips.vue / QueryResultTable.vue 组件**

- [ ] **Step 5: 注册路由并测试**

- [ ] **Step 6: Commit**

```bash
git add backend/ frontend/ && git commit -m "feat: AI chat with NL2SQL entity parsing and export"
```

---

### Task 11: 专项效果看板

**Files:**
- Create: `backend/app/routers/campaign.py`
- Create: `backend/app/services/campaign_service.py`
- Create: `frontend/src/views/CampaignBoard.vue`
- Create: `frontend/src/components/campaign/*.vue`

- [ ] **Step 1: 后端 — 专项看板数据聚合**

聚合维度：KPI 卡片、商机预测类别分布（漏斗图）、渠道归因（饼图）、采购阶段分布、关键角色覆盖、内容效果表、客户跟进表。

- [ ] **Step 2: 前端 — CampaignBoard.vue 页面 + 子组件**

使用 ECharts 渲染图表，参考原型 HTML 中的专项看板布局。

- [ ] **Step 3: Commit**

```bash
git add backend/ frontend/ && git commit -m "feat: campaign dashboard with charts and tables"
```

---

### Task 12: AI 审核队列

**Files:**
- Create: `backend/app/routers/review.py`
- Create: `frontend/src/views/ReviewQueue.vue`
- Create: `frontend/src/components/review/*.vue`

- [ ] **Step 1: 后端 — 审核列表 API**

查询 `dws_review_queue` 表，支持确认/拒绝操作。

- [ ] **Step 2: 前端 — 审核队列页面**

展示待审核的公司名合并建议，支持确认/拒绝/跳过。

- [ ] **Step 3: Commit**

```bash
git add backend/ frontend/ && git commit -m "feat: AI review queue for company name dedup"
```

---

### Task 13: 集成测试与优化

- [ ] **Step 1: 端到端测试**
  - 客户列表：筛选、搜索、分页、导出
  - 客户详情：概览 TAB 各模块、联系人 TAB
  - AI 对话：输入自然语言、查看实体、查看结果、导出
  - 专项看板：图表渲染
  - 审核队列：查看/确认/拒绝

- [ ] **Step 2: 性能优化**
  - 大表查询添加合适索引
  - 前端列表虚拟滚动（如需要）
  - API 响应缓存

- [ ] **Step 3: 样式微调**
  - 对齐原型设计暗色主题
  - 响应式适配

- [ ] **Step 4: Final Commit**

```bash
git add -A && git commit -m "feat: Phase 1 complete - CDP ABM 360 with all P0+P1 features"
```

---

## Verification

1. **后端启动**: `cd backend && uvicorn app.main:app --reload --port 8000`
2. **前端启动**: `cd frontend && npm run dev`
3. **访问**: http://localhost:3000
4. **核心流程验证**:
   - 客户列表加载 → 筛选 → 搜索 → 导出 Excel
   - 点击客户 → 详情概览 TAB → 联系人 TAB
   - AI 对话 → 输入"广东省医疗行业互动3次以上的客户" → 查看实体识别 → 结果列表 → 导出
   - 专项看板图表正确渲染
   - 审核队列可操作
