# MySQL 数据迁移至 ElasticSearch 技术文档

> 适用项目：ruijie-cdp（CDP ABM 360）
> 文档版本：v1.0
> 最后更新：2026-07-07

---

## 1. 概述

将 CDP 系统的 MySQL DWS（数据仓库服务）聚合层数据同步到 ElasticSearch（以下简称 ES），
用于**全文检索**与**聚合分析**。

### 1.1 设计原则

- **MySQL 仍为主存储**：ES 是 DWS 层数据的检索/分析副本，不直接写入业务数据。
- **复用现有 ETL**：每次 ODS → DWS 的 ETL 完成后自动触发 ES 同步，无需独立运维管道。
- **best-effort 容错**：ES 同步失败不影响主 ETL 流程，仅记录日志。
- **零中断切换**：全量同步采用 alias 轮换，切换瞬间对线上检索无感知。

### 1.2 数据范围

迁移对象为 DWS 聚合层全部 4 张核心表：

| DWS 表 | ES 别名（对外查询入口） | 用途 |
|--------|------------------------|------|
| `dws_customer_360` | `cdp_customer_360` | 客户 360 视图（检索 + 聚合） |
| `dws_contact_360` | `cdp_contact_360` | 联系人 360 视图 |
| `dws_interaction_detail` | `cdp_interaction_detail` | 互动明细（行为检索） |
| `dws_contact_mapping` | `cdp_contact_mapping` | 跨系统联系人映射 |

> 索引名（`cdp_*`）由配置项 `ES_INDEX_PREFIX` 决定，可通过前缀隔离多环境。

---

## 2. 系统架构

```
业务系统
   │  (原始数据)
   ▼
ODS 层 (MySQL)  ──ETL 聚合──▶  DWS 层 (MySQL, 主存储)
                                     │
                          ETL 成功后自动同步（alias 轮换 / 增量 upsert）
                                     ▼
                            ElasticSearch (检索 / 分析)
                                     │
                                     ▼
                           前端检索 / 聚合看板 / 高级筛选
```

---

## 3. 索引设计

### 3.1 字段类型映射

| MySQL 类型 | ES 类型 | 说明 |
|-----------|---------|------|
| `VARCHAR` / `TEXT`（中文） | `text` + `cn_analyzer` | 全文检索，并附 `.keyword` 子字段用于精确匹配/聚合 |
| `VARCHAR`（编码、枚举） | `keyword` | 精确匹配、terms 聚合 |
| `INT` / `BIGINT` | `integer` / `long` | 数值 |
| `DECIMAL` | `double` | 金额 |
| `DATETIME` | `date` | 时间范围检索 |
| `TINYINT` | `boolean` | 布尔 |
| `JSON` | `flattened` | 任意结构 JSON，免展开（如 `role_detail`、`top_channels`） |

### 3.2 中文分词

中文全文字段使用 `cn_analyzer` 分析器，由索引 settings 定义：

```json
{
  "analysis": {
    "analyzer": {
      "cn_analyzer": { "type": "<ES_ANALYZER>" }
    }
  }
}
```

- 默认值 `ES_ANALYZER=ik_max_word`（需 ES 安装 IK 分词插件）。
- 若集群未安装 IK 插件，将 `ES_ANALYZER` 改为 `standard` 即可降级为单字/标准分词。

### 3.3 Alias 与物理索引

对外查询统一使用 **alias**（如 `cdp_customer_360`）。全量同步时：

1. 创建带时间戳的物理索引：`cdp_customer_360_20260707xxxxxx`
2. 批量写入数据
3. 原子切换 alias 指向新索引
4. 删除旧物理索引

因此线上检索始终命中 alias，全量重建过程对应用透明。

---

## 4. 同步机制

### 4.1 全量同步（`run_es_full_sync`）

触发场景：手动调用接口，或 ETL 全量/调度（`run_etl`）成功后。

流程：

1. 对每张 DWS 表：读取全量行（分批 `yield_per=2000`）。
2. 转换为 ES 文档（JSON 字段解析、日期/Decimal 归一化），`_id = 主键 id`。
3. 写入新的物理索引，每 2000 条执行一次 `bulk`。
4. alias 原子切换 + 删除旧索引。
5. 重置增量水位（`es_sync_state`）为当前时间。

### 4.2 增量同步（`run_es_incremental_sync`）

触发场景：手动调用接口，或 ETL 增量（`run_incremental_sync`）成功后。

流程：

1. 读取水位表 `es_sync_state.last_sync_time` 作为基准时间 `last`。
2. 对每张表按时间列筛选变化行：
   - `dws_interaction_detail` 用 `etl_time`
   - 其余表用 `updated_at`
3. 以 `doc_as_upsert` 批量 upsert 到对应 alias（`_id = 主键 id`）。
4. 对**小表**（`dws_customer_360`、`dws_contact_360`）执行孤儿删除检测：
   对比 MySQL 当前主键集合与 ES 现有文档 id，删除 ES 中已不存在的文档。
   （`dws_interaction_detail` 通常只增不删，跳过删除检测以保证性能。）
5. 更新水位为本次同步完成时间。

### 4.3 自动触发接入点

在 `backend/app/services/etl_sync.py` 三个 ETL 函数的成功路径末尾，
均通过延迟导入调用 ES 同步（失败仅记录日志，不回滚 ETL）：

| ETL 函数 | 触发 ES 同步类型 |
|----------|------------------|
| `run_full_sync` | `full`（全量重建） |
| `run_incremental_sync` | `incremental`（增量） |
| `run_etl`（调度器每小时） | `full`（全量重建） |

### 4.4 增量水位表

```sql
CREATE TABLE IF NOT EXISTS es_sync_state (
  id INT PRIMARY KEY DEFAULT 1,
  last_sync_time DATETIME NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

由 `es_sync.py` 在首次增量同步时自动创建并初始化（基准时间 `2000-01-01`）。

---

## 5. API 接口

路由前缀：`/api/admin/es`
实现文件：`backend/app/routers/es_sync.py`

### 5.1 全量同步

```
POST /api/admin/es/full
```

手动触发 ES 全量重建。带并发锁，重复调用返回 `409 Conflict`。

**响应示例：**

```json
{
  "status": "ok",
  "message": "ES full sync completed",
  "details": {
    "dws_customer_360": 1200,
    "dws_contact_360": 8600,
    "dws_interaction_detail": 45000,
    "dws_contact_mapping": 9000
  }
}
```

### 5.2 增量同步

```
POST /api/admin/es/increment
```

手动触发 ES 增量同步。带并发锁。

**响应示例：**

```json
{
  "status": "ok",
  "message": "ES incremental sync completed",
  "details": {
    "dws_customer_360": { "upserted": 12, "pruned": 1 },
    "dws_contact_360": { "upserted": 30, "pruned": 0 },
    "dws_interaction_detail": { "upserted": 200, "pruned": 0 },
    "dws_contact_mapping": { "upserted": 15, "pruned": 0 }
  }
}
```

### 5.3 健康检查

```
GET /api/admin/es/health
```

返回 ES 集群信息及各索引文档数，用于迁移前后数据量核对。

**响应示例：**

```json
{
  "cluster": "ruijie-es-prod",
  "version": "8.13.0",
  "indices": {
    "dws_customer_360":     { "alias": "cdp_customer_360", "docs": 1200, "exists": true },
    "dws_contact_360":      { "alias": "cdp_contact_360", "docs": 8600, "exists": true },
    "dws_interaction_detail": { "alias": "cdp_interaction_detail", "docs": 45000, "exists": true },
    "dws_contact_mapping":  { "alias": "cdp_contact_mapping", "docs": 9000, "exists": true }
  }
}
```

---

## 6. 配置说明

### 6.1 后端配置（`backend/app/config.py`）

所有 ES 配置通过环境变量注入：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ES_HOST` | 空 | ES 主机地址 |
| `ES_PORT` | `9200` | ES 端口 |
| `ES_USER` | `elastic` | 账号 |
| `ES_PASSWORD` | 空 | 密码 |
| `ES_SCHEME` | `https` | `http` / `https` |
| `ES_INDEX_PREFIX` | `cdp_` | 索引名前缀 |
| `ES_VERIFY_CERTS` | `false` | 是否校验 TLS 证书（自签证书设为 `false`） |
| `ES_ANALYZER` | `ik_max_word` | 中文分析器（无 IK 插件时改 `standard`） |

### 6.2 部署配置

`docker-compose.yml` 的 `backend` 服务已注入上述 ES 环境变量：

```yaml
environment:
  - ES_HOST=${ES_HOST:-}
  - ES_PORT=${ES_PORT:-9200}
  - ES_USER=${ES_USER:-elastic}
  - ES_PASSWORD=${ES_PASSWORD:-}
  - ES_SCHEME=${ES_SCHEME:-https}
  - ES_INDEX_PREFIX=${ES_INDEX_PREFIX:-cdp_}
  - ES_VERIFY_CERTS=${ES_VERIFY_CERTS:-false}
  - ES_ANALYZER=${ES_ANALYZER:-ik_max_word}
```

本地开发可将连接信息写入项目根 `.env`（已被 `.gitignore` 忽略，含密码，请勿提交）。

### 6.3 依赖

`backend/requirements.txt` 新增：

```
elasticsearch>=8.0
```

安装：`pip install -r backend/requirements.txt`

---

## 7. 使用步骤

### 7.1 首次全量迁移

1. 安装依赖、配置 ES 环境变量、确认 ES 已安装 IK 插件（或 `ES_ANALYZER=standard`）。
2. 启动后端后调用：

```bash
curl -X POST "http://<backend-host>:8000/api/admin/es/full"
curl -X POST "http://localhost:8000/api/admin/es/full"
```

3. 核对数据量：

```bash
curl "http://<backend-host>:8000/api/admin/es/health"
curl "http://localhost:8000/api/admin/es/health"
```

### 7.2 持续同步

- **自动**：每次触发 ETL（`/api/admin/etl/full`、`/api/admin/etl/increment` 或调度器每小时执行）
  成功后自动同步 ES，无需人工干预。
- **手动**：增量数据可随时调用 `POST /api/admin/es/increment` 立即同步。

---

## 8. 注意事项

1. **鉴权**：`/api/admin/es/*` 与既有 `/api/admin/etl/*` 同处于无鉴权前缀下（CORS 全开）。
   生产环境应在网关或中间件层增加访问控制。
2. **IK 插件**：中文检索质量依赖 IK 分词插件；未安装时务必将 `ES_ANALYZER` 设为 `standard`，
   否则创建索引会失败。
3. **大表性能**：`dws_interaction_detail` 可能数据量较大，全量同步耗时较长；
   增量同步跳过其删除检测，仅做 upsert。
4. **水位基准**：全量同步会重置增量水位。若 ES 数据需要回退到某一历史时刻，
   可手动调整 `es_sync_state.last_sync_time` 后执行增量同步。
5. **失败隔离**：ES 同步异常被捕获并记录日志，不会中断 ETL 主流程；
   可通过后端日志排查同步失败原因。

---

## 9. 关键文件索引

| 文件 | 职责 |
|------|------|
| `backend/app/services/es_sync.py` | ES 客户端、索引 mapping、全量/增量同步、水位管理 |
| `backend/app/routers/es_sync.py` | `/api/admin/es/*` 管理接口 |
| `backend/app/config.py` | ES 连接配置 |
| `backend/app/services/etl_sync.py` | ETL 主流程，成功后触发 ES 同步 |
| `backend/app/main.py` | 注册 ES 路由 |
| `docker-compose.yml` | backend 服务 ES 环境变量 |
| `backend/requirements.txt` | `elasticsearch` 依赖 |
