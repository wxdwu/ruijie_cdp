# CDP ABM 360 — API 接口汇总

> 文档生成日期：2026-07-12
> 后端框架：FastAPI（Python）；文档基于 `backend/app/routers/*` 全部路由自动整理。

---

## 0. 服务与数据库配置

### 0.1 数据库配置（`.env` / `config.py`）

当前后端通过 `backend/.env`（若存在）或 `app/config.py` 中的默认值连接 MySQL。
工作区中仅存在 `backend/.env.example`，因此运行时使用 `config.py` 的默认值，等效配置如下：

```ini
DB_HOST=192.168.159.22
DB_PORT=33307
DB_USER=app_cdp
DB_PASSWORD=123456
DB_NAME=app_cdp
```

> 说明：`config.py` 会优先加载 `backend/.env`（位于 `app/` 的上一级目录），
> 若需覆盖，可在 `backend/.env` 中写入上述变量。
> 当前为测试环境，**每个表仅保留约 1000 条数据**，便于快速验证接口。

ElasticSearch 默认未配置（生产需在 `.env` 中设置 `ES_HOST` 等），因此 ES 相关接口在测试环境会报错。

### 0.2 服务地址

| 环境 | BASE_URL | 说明 |
| --- | --- | --- |
| 本地开发 | `http://localhost:8000` | `uvicorn app.main:app --reload --port 8000` |
| 远程 | `http://192.168.159.22:28080` | 前端 `config.js` 的 `remote` 预设 |

所有接口统一以 `/api` 为前缀。下文 `curl` 示例均以本地 `BASE=http://localhost:8000` 为例。

```bash
BASE=http://localhost:8000
```

### 0.3 启动命令

```bash
cd ruijie-cdp/backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
# 浏览器打开 http://localhost:8000/docs 可查看 Swagger 在线文档
```

### 0.4 约定

- 列表类接口统一返回 `{ "total": int, "items": [...] }` 或带分页字段。
- 时间范围参数（如 `start_date` / `end_date`）格式为 `YYYY-MM-DD`。
- POST 接口 `Content-Type` 均为 `application/json`。
- 涉及写库 / 合并 / 同步的接口为**危险操作**，请在测试库执行。

---

## 1. 健康检查 / 系统管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务健康检查 |
| POST | `/api/admin/etl/run` | 手动触发一次 ETL（全量逻辑，带并发锁） |
| GET | `/demo` | 演示页（HTML 原型，无导航入口） |

### 1.1 健康检查

```bash
curl -X GET "$BASE/api/health"
```

返回：`{ "status": "ok", "service": "CDP ABM 360" }`

### 1.2 手动触发 ETL

```bash
curl -X POST "$BASE/api/admin/etl/run"
```

返回：`{ "status": "ok", "stats": { ... } }`；若已有 ETL 在跑返回 `409`。

---

## 2. 客户列表模块（`/api/customers`）

> 路由文件：`app/routers/customer_list.py`、`app/routers/customer_detail.py`
> 主表：`dws_customer_360`、`dws_contact_360`、`dws_interaction_detail`、`ods_crm_opportunity_day`

### 2.1 客户列表（分页 + 多条件筛选）

`GET /api/customers`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| keyword | str | 按客户名称模糊搜索 |
| special_project | str | 按 campaigns_tag 筛选（专项） |
| industry / region / owner | str | 精确筛选（行业 / 地区 / 负责人） |
| region_keyword / owner_keyword | str | 模糊搜索（地区 / 负责人） |
| stage | str | 采购阶段 |
| intent_level | str | 意向等级（高/中/低） |
| interaction_min | int | 指定周期内最小互动次数 |
| interaction_period | int | 互动统计周期天数（30/60/90/180/365/1095，默认 30） |
| attribute | str | 重点客户标记：`heavy`=H，`non_heavy`=非H |
| channel | str | 最近互动渠道 |
| sort | str | 排序，如 `intent_score desc` |
| page / size | int | 页码（≥1）/ 每页条数（≤100，默认 20） |

```bash
curl -X GET "$BASE/api/customers?keyword=科技&industry=制造&intent_level=高&page=1&size=20"

curl -X GET "$BASE/api/customers?interaction_min=5&interaction_period=90&sort=intent_score%20desc"
```

返回：`{ "total": int, "items": [...], "filters_applied": {...} }`

### 2.2 筛选选项（下拉枚举值）

`GET /api/customers/filter-options`

```bash
curl -X GET "$BASE/api/customers/filter-options"
```

返回：`{ "industries": [...], "regions": [...], "owners": [...], "stages": [...], "intent_levels": [...], "channels": [...] }`

### 2.3 客户统计汇总

`GET /api/customers/statistics`

```bash
curl -X GET "$BASE/api/customers/statistics"
```

返回：每个客户的联系人 / 互动统计列表 + `summary`（total_contacts、total_interactions）。

### 2.4 按名称查询统计

`GET /api/customers/statistics/by-name?customer_name=xxx`（支持模糊匹配，取首条）

```bash
curl -X GET "$BASE/api/customers/statistics/by-name?customer_name=魏桥"
```

返回：`{ "status": "success|not_found", "data": { "customer_name", "contact_count", "interaction_count_total" } }`

### 2.5 导出客户列表（Excel）

`GET /api/customers/export`（筛选参数同 2.1，返回 `.xlsx` 文件流）

```bash
curl -X GET "$BASE/api/customers/export?industry=制造" -o customers_export.xlsx
```

---

## 3. 客户详情模块（`/api/customers/{id}`）

### 3.1 客户 360 详情

`GET /api/customers/{id}`

```bash
curl -X GET "$BASE/api/customers/1"
```

返回：客户全字段 + `interaction_count_30d` + 最近拜访信息。

### 3.2 联系人列表

`GET /api/customers/{id}/contacts`

```bash
curl -X GET "$BASE/api/customers/1/contacts"
```

返回：`{ "customer_id", "customer_name", "contacts": [...], "total" }`

### 3.3 互动时间线

`GET /api/customers/{id}/interactions?limit=50`（limit ≤ 500）

```bash
curl -X GET "$BASE/api/customers/1/interactions?limit=100"
```

返回：`{ "customer_id", "customer_name", "interactions": [...], "total" }`

### 3.4 CRM 商机

`GET /api/customers/{id}/opportunities`

```bash
curl -X GET "$BASE/api/customers/1/opportunities"
```

返回：`{ "customer_id", "customer_name", "opportunities": [...], "total" }`

### 3.5 AI 洞察（规则引擎）

`GET /api/customers/{id}/ai-insight`

```bash
curl -X GET "$BASE/api/customers/1/ai-insight"
```

返回：`{ "business_conclusion": [...], "evidence": {...}, "recommendation", "recommendations", "total_candidates", "source" }`

---

## 4. 营销活动看板模块（`/api/campaign`）

> 路由文件：`app/routers/campaign.py`，全部为只读聚合查询。

通用筛选参数（大部分接口支持）：`campaign_tag`、`industry`、`channel`、`start_date`、`end_date`。

### 4.1 看板筛选选项

`GET /api/campaign/filter-options`

```bash
curl -X GET "$BASE/api/campaign/filter-options"
```

返回：campaigns / industries / channels 列表 + 互动日期范围 `min_date` / `max_date`。

### 4.2 KPI 卡片

`GET /api/campaign/kpis`

```bash
curl -X GET "$BASE/api/campaign/kpis?campaign_tag=xxx&start_date=2026-01-01&end_date=2026-06-30&channel=邮件"
```

返回：`{ "total_customers", "active_customers", "opportunity_count", "total_amount", "deal_customers" }`

### 4.3 商机预测分布

`GET /api/campaign/funnel-distribution`

```bash
curl -X GET "$BASE/api/campaign/funnel-distribution?industry=制造"
```

返回：`{ "categories": [...], "stages": [...], "total" }`

### 4.4 渠道分布

`GET /api/campaign/channel-distribution`

```bash
curl -X GET "$BASE/api/campaign/channel-distribution?campaign_tag=xxx"
```

返回：`{ "channels": [...], "total" }`

### 4.5 关键角色覆盖

`GET /api/campaign/role-coverage`

```bash
curl -X GET "$BASE/api/campaign/role-coverage"
```

返回：`{ "roles": [...], "total_customers" }`

### 4.6 采购阶段分布

`GET /api/campaign/stage-distribution`

```bash
curl -X GET "$BASE/api/campaign/stage-distribution?industry=制造"
```

返回：`{ "stages": [...], "total" }`

### 4.7 标签信号

`GET /api/campaign/tag-signals`

```bash
curl -X GET "$BASE/api/campaign/tag-signals"
```

返回：`{ "signals": [...] }`（默认取行业 Top 8）

### 4.8 内容 / 主题互动效果

`GET /api/campaign/content-effect`

```bash
curl -X GET "$BASE/api/campaign/content-effect?channel=邮件&start_date=2026-01-01&end_date=2026-06-30"
```

返回：`{ "data": [...] }`（触达 / 打开 / 点击 / MQL 统计）

### 4.9 按阶段客户跟进列表

`GET /api/campaign/customers-by-stage`（分页 + 筛选）

| 参数 | 说明 |
| --- | --- |
| stage / owner / keyword | 阶段 / 负责人 / 名称模糊 |
| page / page_size | 默认 1 / 10（≤100） |
| campaign_tag / industry / channel / start_date / end_date | 通用筛选 |

```bash
curl -X GET "$BASE/api/campaign/customers-by-stage?stage=阶段3&page=1&page_size=10"

curl -X GET "$BASE/api/campaign/customers-by-stage?keyword=科技&owner=张三"
```

返回：`{ "grouped", "flat", "total", "page", "page_size", "total_pages", "filter_options": {...} }`

---

## 5. AI 对话模块（`/api/ai`）

> 路由文件：`app/routers/ai_chat.py`，依赖 LLM（`LLM_API_KEY` / `LLM_BASE_URL`）。

### 5.1 自然语言解析

`POST /api/ai/parse`

请求体：`{ "query": "高意向的制造业客户", "history": [] }`

```bash
curl -X POST "$BASE/api/ai/parse" \
  -H "Content-Type: application/json" \
  -d '{"query":"高意向的制造业客户","history":[]}'
```

返回：`{ "query", "entities", "intent" }`

### 5.2 对话（含客户结果）

`POST /api/ai/chat`

请求体：`{ "query": "最近互动最多的客户", "history": [] }`

```bash
curl -X POST "$BASE/api/ai/chat" \
  -H "Content-Type: application/json" \
  -d '{"query":"最近互动最多的客户","history":[]}'
```

返回：`{ "query", "entities", "response", "customers", "intent", "preprocessed_query", ["data", "target_table"] }`

### 5.3 导出对话查询结果（Excel）

`POST /api/ai/chat/export`

请求体：`{ "query": "...", "entities": {...}|"structured_query": {...}, "target_table": "dws_customer_360" }`

```bash
curl -X POST "$BASE/api/ai/chat/export" \
  -H "Content-Type: application/json" \
  -d '{"query":"高意向客户","entities":{"intent_level":"高"},"target_table":"dws_customer_360"}' \
  -o ai_chat_export.xlsx
```

---

## 6. 去重审核模块（`/api/review`）

> 路由文件：`app/routers/review.py`，依赖 `app/services/company_dedup.py`。
> 审核队列表 `review_candidate` 不存在时接口会自动建表。

### 6.1 审核项列表（分页）

`GET /api/review`

| 参数 | 说明 |
| --- | --- |
| review_type | company_merge / contact_merge / data_quality |
| status | pending / auto_merged / rejected / need_review |
| page / size | 默认 1 / 20（≤100） |

```bash
curl -X GET "$BASE/api/review?status=pending&page=1&size=20"

curl -X GET "$BASE/api/review?review_type=company_merge"
```

返回：`{ "total", "items": [...], "page", "size" }`（每项含候选双方详情）。

### 6.2 审核统计

`GET /api/review/stats`

```bash
curl -X GET "$BASE/api/review/stats"
```

返回：`{ "pending", "auto_merged", "rejected", "need_review", "total" }`

### 6.3 通过并合并

`POST /api/review/{id}/approve`

```bash
curl -X POST "$BASE/api/review/1/approve"
```

返回：`{ "success": true, "id", "status": "auto_merged", "message" }`

### 6.4 拒绝合并

`POST /api/review/{id}/reject`

```bash
curl -X POST "$BASE/api/review/1/reject"
```

返回：`{ "success": true, "id", "status": "rejected", "message" }`

### 6.5 批量通过

`POST /api/review/batch-approve`，请求体 `{ "ids": [1,2,3] }`

```bash
curl -X POST "$BASE/api/review/batch-approve" \
  -H "Content-Type: application/json" \
  -d '{"ids":[1,2,3]}'
```

### 6.6 批量拒绝

`POST /api/review/batch-reject`，请求体 `{ "ids": [1,2,3] }`

```bash
curl -X POST "$BASE/api/review/batch-reject" \
  -H "Content-Type: application/json" \
  -d '{"ids":[1,2,3]}'
```

### 6.7 触发去重

`POST /api/review/run-dedup`（计算相似公司、打分并写入审核队列）

```bash
curl -X POST "$BASE/api/review/run-dedup"
```

### 6.8 去重进度

`GET /api/review/dedup-progress`

```bash
curl -X GET "$BASE/api/review/dedup-progress"
```

---

## 7. ETL 数据同步模块（`/api/admin/etl`）

> 路由文件：`app/routers/sync.py`，记录写入 `dws_sync_log`。带并发锁，运行中再次触发返回 `409`。

### 7.1 全量同步

`POST /api/admin/etl/full?trigger_by=system`

```bash
curl -X POST "$BASE/api/admin/etl/full?trigger_by=tester"
```

返回：`{ "status": "ok", "sync_id": int, "message": "..." }`

### 7.2 增量同步

`POST /api/admin/etl/increment?trigger_by=system`

```bash
curl -X POST "$BASE/api/admin/etl/increment?trigger_by=tester"
```

### 7.3 最近同步状态

`GET /api/admin/etl/status`

```bash
curl -X GET "$BASE/api/admin/etl/status"
```

返回：最新一条 `dws_sync_log` 的 sync_id / type / status / 耗时 / 行数。

### 7.4 同步历史

`GET /api/admin/etl/history?limit=10`

```bash
curl -X GET "$BASE/api/admin/etl/history?limit=20"
```

返回：`{ "total", "records": [...] }`

---

## 8. ElasticSearch 同步模块（`/api/admin/es`）

> 路由文件：`app/routers/es_sync.py`。**需先配置 ES（`ES_HOST` 等）**，否则接口报错。

### 8.1 ES 全量同步

`POST /api/admin/es/full?trigger_by=system`

```bash
curl -X POST "$BASE/api/admin/es/full?trigger_by=tester"
```

### 8.2 ES 增量同步

`POST /api/admin/es/increment?trigger_by=system`

```bash
curl -X POST "$BASE/api/admin/es/increment?trigger_by=tester"
```

### 8.3 ES 健康 / 索引状态

`GET /api/admin/es/health`

```bash
curl -X GET "$BASE/api/admin/es/health"
```

---

## 9. ElasticSearch 通用 CRUD（`/api/admin/es`）

> 路由文件：`app/routers/es_crud.py`。`index` 可传别名（如 `cdp_customer_360`）。

### 9.1 批量新增

`POST /api/admin/es/{index}/batch-create`

```bash
curl -X POST "$BASE/api/admin/es/cdp_customer_360/batch-create" \
  -H "Content-Type: application/json" \
  -d '{"docs":[{"id":1,"customer_name":"示例科技"}],"batch_size":5000}'
```

### 9.2 按 id 查询

`GET /api/admin/es/{index}/{doc_id}`

```bash
curl -X GET "$BASE/api/admin/es/cdp_customer_360/1"
```

### 9.3 按 DSL 检索

`POST /api/admin/es/{index}/search`

```bash
curl -X POST "$BASE/api/admin/es/cdp_customer_360/search" \
  -H "Content-Type: application/json" \
  -d '{"query":{"match_all":{}},"size":10}'
```

### 9.4 局部更新

`PUT /api/admin/es/{index}/{doc_id}`

```bash
curl -X PUT "$BASE/api/admin/es/cdp_customer_360/1" \
  -H "Content-Type: application/json" \
  -d '{"intent_level":"高"}'
```

### 9.5 批量更新 / upsert

`POST /api/admin/es/{index}/batch-update`

```bash
curl -X POST "$BASE/api/admin/es/cdp_customer_360/batch-update" \
  -H "Content-Type: application/json" \
  -d '{"docs":[{"id":1,"intent_level":"高"}],"batch_size":5000}'
```

### 9.6 按 id 删除

`DELETE /api/admin/es/{index}/{doc_id}`

```bash
curl -X DELETE "$BASE/api/admin/es/cdp_customer_360/1"
```

### 9.7 批量删除

`POST /api/admin/es/{index}/batch-delete`

```bash
curl -X POST "$BASE/api/admin/es/cdp_customer_360/batch-delete" \
  -H "Content-Type: application/json" \
  -d '{"ids":["1","2"],"batch_size":5000}'
```

### 9.8 按查询删除

`POST /api/admin/es/{index}/delete-by-query`

```bash
curl -X POST "$BASE/api/admin/es/cdp_customer_360/delete-by-query" \
  -H "Content-Type: application/json" \
  -d '{"query":{"term":{"intent_level":"低"}}}'
```

---

## 10. 连接池管理模块（`/api/pool`）

> 路由文件：`app/routers/pool.py`，用于运维监控 MySQL 连接池与熔断器。

### 10.1 池运行状态

`GET /api/pool/status`

```bash
curl -X GET "$BASE/api/pool/status"
```

### 10.2 池配置参数

`GET /api/pool/config`

```bash
curl -X GET "$BASE/api/pool/config"
```

### 10.3 扩展统计（状态 + 配置 + 重试计数）

`GET /api/pool/stats`

```bash
curl -X GET "$BASE/api/pool/stats"
```

### 10.4 重置连接池（危险）

`POST /api/pool/reset?confirm=true`

```bash
curl -X POST "$BASE/api/pool/reset?confirm=true"
```

### 10.5 强制熔断器状态

`POST /api/pool/circuit-breaker/{target_state}`（`open` / `closed` / `half_open`）

```bash
curl -X POST "$BASE/api/pool/circuit-breaker/open"

curl -X POST "$BASE/api/pool/circuit-breaker/closed"
```

### 10.6 重置重试计数器

`POST /api/pool/retry-counter/reset`

```bash
curl -X POST "$BASE/api/pool/retry-counter/reset"
```

### 10.7 预热连接池

`POST /api/pool/warmup?min_connections=20`（≤ pool_size）

```bash
curl -X POST "$BASE/api/pool/warmup?min_connections=20"
```

---

## 11. 表数据量监控模块（`/api/admin/monitor`）

> 路由文件：`app/routers/monitor.py`，统计所有已注册表的数据量并写入 `dws_sync_obs`。

### 11.1 触发一次监控

`POST /api/admin/monitor/run`

```bash
curl -X POST "$BASE/api/admin/monitor/run"
```

返回：`{ "status": "ok", "count": int, "records": [...] }`

### 11.2 最近快照

`GET /api/admin/monitor/latest`

```bash
curl -X GET "$BASE/api/admin/monitor/latest"
```

返回：每个表最新一次的数据量快照。

### 11.3 监控历史

`GET /api/admin/monitor/history?limit=100`

```bash
curl -X GET "$BASE/api/admin/monitor/history?limit=50"
```

---

## 附录：接口速查表

| 模块 | 方法 | 路径 |
| --- | --- | --- |
| 系统 | GET | `/api/health` |
| 系统 | POST | `/api/admin/etl/run` |
| 客户列表 | GET | `/api/customers` |
| 客户列表 | GET | `/api/customers/filter-options` |
| 客户列表 | GET | `/api/customers/statistics` |
| 客户列表 | GET | `/api/customers/statistics/by-name` |
| 客户列表 | GET | `/api/customers/export` |
| 客户详情 | GET | `/api/customers/{id}` |
| 客户详情 | GET | `/api/customers/{id}/contacts` |
| 客户详情 | GET | `/api/customers/{id}/interactions` |
| 客户详情 | GET | `/api/customers/{id}/opportunities` |
| 客户详情 | GET | `/api/customers/{id}/ai-insight` |
| 活动看板 | GET | `/api/campaign/filter-options` |
| 活动看板 | GET | `/api/campaign/kpis` |
| 活动看板 | GET | `/api/campaign/funnel-distribution` |
| 活动看板 | GET | `/api/campaign/channel-distribution` |
| 活动看板 | GET | `/api/campaign/role-coverage` |
| 活动看板 | GET | `/api/campaign/stage-distribution` |
| 活动看板 | GET | `/api/campaign/tag-signals` |
| 活动看板 | GET | `/api/campaign/content-effect` |
| 活动看板 | GET | `/api/campaign/customers-by-stage` |
| AI | POST | `/api/ai/parse` |
| AI | POST | `/api/ai/chat` |
| AI | POST | `/api/ai/chat/export` |
| 去重 | GET | `/api/review` |
| 去重 | GET | `/api/review/stats` |
| 去重 | POST | `/api/review/{id}/approve` |
| 去重 | POST | `/api/review/{id}/reject` |
| 去重 | POST | `/api/review/batch-approve` |
| 去重 | POST | `/api/review/batch-reject` |
| 去重 | POST | `/api/review/run-dedup` |
| 去重 | GET | `/api/review/dedup-progress` |
| ETL | POST | `/api/admin/etl/full` |
| ETL | POST | `/api/admin/etl/increment` |
| ETL | GET | `/api/admin/etl/status` |
| ETL | GET | `/api/admin/etl/history` |
| ES同步 | POST | `/api/admin/es/full` |
| ES同步 | POST | `/api/admin/es/increment` |
| ES同步 | GET | `/api/admin/es/health` |
| ES CRUD | POST | `/api/admin/es/{index}/batch-create` |
| ES CRUD | GET | `/api/admin/es/{index}/{doc_id}` |
| ES CRUD | POST | `/api/admin/es/{index}/search` |
| ES CRUD | PUT | `/api/admin/es/{index}/{doc_id}` |
| ES CRUD | POST | `/api/admin/es/{index}/batch-update` |
| ES CRUD | DELETE | `/api/admin/es/{index}/{doc_id}` |
| ES CRUD | POST | `/api/admin/es/{index}/batch-delete` |
| ES CRUD | POST | `/api/admin/es/{index}/delete-by-query` |
| 连接池 | GET | `/api/pool/status` |
| 连接池 | GET | `/api/pool/config` |
| 连接池 | GET | `/api/pool/stats` |
| 连接池 | POST | `/api/pool/reset` |
| 连接池 | POST | `/api/pool/circuit-breaker/{target_state}` |
| 连接池 | POST | `/api/pool/retry-counter/reset` |
| 连接池 | POST | `/api/pool/warmup` |
| 监控 | POST | `/api/admin/monitor/run` |
| 监控 | GET | `/api/admin/monitor/latest` |
| 监控 | GET | `/api/admin/monitor/history` |
