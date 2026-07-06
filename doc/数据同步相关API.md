# 数据同步相关 API 文档

## 目录

- [1. 概述](#1-概述)
- [2. 数据表结构](#2-数据表结构)
- [3. API 端点](#3-api-端点)
  - [3.1 触发全量同步](#31-触发全量同步)
  - [3.2 触发增量同步](#32-触发增量同步)
  - [3.3 获取最新同步状态](#33-获取最新同步状态)
  - [3.4 获取同步历史](#34-获取同步历史)
- [4. 同步机制说明](#4-同步机制说明)
- [5. 错误处理](#5-错误处理)

---

## 1. 概述

数据同步模块负责将 ODS（操作数据存储）层的原始数据聚合到 DWS（数据仓库服务）层，供上层业务查询使用。

**核心功能：**
- 全量同步：TRUNCATE + 全量重载
- 增量同步：UPSERT + 删除检测
- 同步日志记录：追踪每次同步的状态和统计信息

**路由前缀：** `/api/admin/etl`

**并发控制：** 使用 `asyncio.Lock()` 防止重叠同步，同一时间只能运行一个同步任务。

---

## 2. 数据表结构

### 2.1 dws_sync_log - 同步日志表

记录每次同步的详细日志信息。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | BIGINT AUTO_INCREMENT | 主键 |
| sync_type | VARCHAR(16) | 同步类型：`full` 或 `incremental` |
| trigger_by | VARCHAR(64) | 触发人，默认 `system` |
| status | VARCHAR(16) | 状态：`running` / `success` / `failed` |
| start_time | DATETIME | 同步开始时间 |
| end_time | DATETIME | 同步结束时间（可为空） |
| rows_synced | INT | 同步行数 |
| error_message | TEXT | 错误信息（失败时记录） |
| details | JSON | 步骤级统计信息 |
| created_at | DATETIME | 记录创建时间 |

**建表语句：**
```sql
CREATE TABLE IF NOT EXISTS dws_sync_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  sync_type VARCHAR(16) NOT NULL COMMENT 'full|incremental',
  trigger_by VARCHAR(64) DEFAULT 'system' COMMENT '触发人',
  status VARCHAR(16) NOT NULL COMMENT 'running|success|failed',
  start_time DATETIME NOT NULL COMMENT '同步开始时间',
  end_time DATETIME COMMENT '同步结束时间',
  rows_synced INT DEFAULT 0 COMMENT '同步行数',
  error_message TEXT COMMENT '错误信息',
  details JSON COMMENT '步骤级统计信息',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2.2 dws_sync_meta - 同步元数据存储表

记录每个 ODS 表的上次同步时间，用于增量同步的时间戳追踪。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| table_name | VARCHAR(128) | ODS 表名（主键） |
| last_sync_time | DATETIME | 上次同步截止 ETL 时间 |
| last_run_time | DATETIME | 上次执行时间 |
| rows_synced | INT | 上次同步行数 |
| status | VARCHAR(16) | 状态：`success` / `error` |

**建表语句：**
```sql
CREATE TABLE IF NOT EXISTS dws_sync_meta (
  table_name VARCHAR(128) PRIMARY KEY,
  last_sync_time DATETIME NOT NULL,
  last_run_time DATETIME NOT NULL,
  rows_synced INT DEFAULT 0,
  status VARCHAR(16) DEFAULT 'success'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 3. API 端点

### 3.1 触发全量同步

触发全量数据同步（TRUNCATE + 全量重载）。

**端点：** `POST /api/admin/etl/full`

**请求参数：**

| 参数名 | 类型 | 位置 | 必填 | 说明 |
|--------|------|------|------|------|
| trigger_by | string | query | 否 | 触发人，默认 `system` |

**请求示例：**
```bash
curl -X POST "http://localhost:8000/api/admin/etl/full?trigger_by=admin"
```

**响应模型：** `SyncTriggerResponse`

| 字段名 | 类型 | 说明 |
|--------|------|------|
| status | string | 状态，成功时为 `ok` |
| sync_id | int | 同步日志 ID（dws_sync_log.id） |
| message | string | 响应消息 |

**响应示例：**
```json
{
  "status": "ok",
  "sync_id": 123,
  "message": "Full sync completed in 120.5s"
}
```

**错误响应：**
- `409 Conflict`：已有同步任务正在运行
- `500 Internal Server Error`：同步执行失败

---

### 3.2 触发增量同步

触发增量数据同步（UPSERT + 删除检测）。

**端点：** `POST /api/admin/etl/increment`

**请求参数：**

| 参数名 | 类型 | 位置 | 必填 | 说明 |
|--------|------|------|------|------|
| trigger_by | string | query | 否 | 触发人，默认 `system` |

**请求示例：**
```bash
curl -X POST "http://localhost:8000/api/admin/etl/increment?trigger_by=admin"
```

**响应模型：** `SyncTriggerResponse`

| 字段名 | 类型 | 说明 |
|--------|------|------|
| status | string | 状态，成功时为 `ok` |
| sync_id | int | 同步日志 ID（dws_sync_log.id） |
| message | string | 响应消息 |

**响应示例：**
```json
{
  "status": "ok",
  "sync_id": 124,
  "message": "Incremental sync completed in 45.2s"
}
```

**错误响应：**
- `409 Conflict`：已有同步任务正在运行
- `500 Internal Server Error`：同步执行失败

---

### 3.3 获取最新同步状态

获取最近一次同步的状态信息。

**端点：** `GET /api/admin/etl/status`

**请求参数：** 无

**请求示例：**
```bash
curl "http://localhost:8000/api/admin/etl/status"
```

**响应字段：**

| 字段名 | 类型 | 说明 |
|--------|------|------|
| sync_id | int | 同步日志 ID |
| sync_type | string | 同步类型：`full` 或 `incremental` |
| trigger_by | string | 触发人 |
| status | string | 状态：`running` / `success` / `failed` / `no_sync_found` |
| start_time | string | 同步开始时间（ISO 格式） |
| end_time | string | 同步结束时间（ISO 格式） |
| elapsed_seconds | float | 同步耗时（秒） |
| rows_synced | int | 同步行数 |
| error_message | string | 错误信息 |

**响应示例：**
```json
{
  "sync_id": 123,
  "sync_type": "full",
  "trigger_by": "admin",
  "status": "success",
  "start_time": "2026-07-06 10:00:00",
  "end_time": "2026-07-06 10:02:00",
  "elapsed_seconds": 120.5,
  "rows_synced": 50000,
  "error_message": null
}
```

**无同步记录时的响应：**
```json
{
  "status": "no_sync_found"
}
```

---

### 3.4 获取同步历史

获取同步历史记录列表（按时间倒序）。

**端点：** `GET /api/admin/etl/history`

**请求参数：**

| 参数名 | 类型 | 位置 | 必填 | 说明 |
|--------|------|------|------|------|
| limit | int | query | 否 | 返回记录数，默认 10，最大 100 |

**请求示例：**
```bash
curl "http://localhost:8000/api/admin/etl/history?limit=20"
```

**响应模型：** `SyncHistoryResponse`

| 字段名 | 类型 | 说明 |
|--------|------|------|
| total | int | 同步历史总条数 |
| records | array | 同步历史记录数组 |

**records 数组元素字段：**

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | int | 同步日志 ID |
| sync_type | string | 同步类型：`full` 或 `incremental` |
| trigger_by | string | 触发人 |
| status | string | 状态：`running` / `success` / `failed` |
| start_time | string | 同步开始时间 |
| end_time | string | 同步结束时间 |
| elapsed_seconds | float | 同步耗时（秒） |
| rows_synced | int | 同步行数 |
| error_message | string | 错误信息 |

**响应示例：**
```json
{
  "total": 50,
  "records": [
    {
      "id": 124,
      "sync_type": "incremental",
      "trigger_by": "admin",
      "status": "success",
      "start_time": "2026-07-06 10:05:00",
      "end_time": "2026-07-06 10:05:45",
      "elapsed_seconds": 45.2,
      "rows_synced": 5000,
      "error_message": null
    },
    {
      "id": 123,
      "sync_type": "full",
      "trigger_by": "system",
      "status": "success",
      "start_time": "2026-07-06 10:00:00",
      "end_time": "2026-07-06 10:02:00",
      "elapsed_seconds": 120.5,
      "rows_synced": 50000,
      "error_message": null
    }
  ]
}
```

---

## 4. 同步机制说明

### 4.1 全量同步流程

全量同步使用**双表轮换机制**（Double Table Rotation），确保同步期间数据可读。

**流程步骤：**

1. **Step 0：确保备份表存在**
   - 检查并创建 `_backup` 后缀的备份表

2. **Step 1：准备备份表**
   - 将主表与备份表轮换
   - 备份表变为可写状态，用于构建新数据

3. **Step 2-4：构建 DWS 表**
   - 构建 `dws_contact_mapping`（联系人映射）
   - 构建 `dws_interaction_detail`（互动详情）
   - 构建 `dws_customer_360`（客户 360 视图）
   - 构建 `dws_contact_360`（联系人 360 视图）

4. **Step 5：聚合 ods_key_customer（重要客户）**
   - 更新已有客户的 `industry` 和 `attribute` 字段
   - 插入新增客户（ods_key_customer 中有但 dws_customer_360 中没有的客户）

5. **Step 6：轮换表**
   - 将备份表（含新数据）轮换为主表
   - 将原主表轮换为备份表

6. **Step 7：清理**
   - 删除临时表
   - 更新同步日志

**双表轮换示意图：**
```
初始状态：
  main_table (对外提供服务)
  backup_table (备份)

同步开始时：
  main_table (继续对外提供服务)
  backup_table (清空，用于构建新数据)

同步完成后：
  main_table (原 backup_table，含新数据，对外提供服务)
  backup_table (原 main_table，变为备份)
```

### 4.2 增量同步流程

增量同步只处理自上次同步以来变化的记录，提高效率。

**流程步骤：**

1. **获取同步批次 ID**
   - 使用 Unix 时间戳（毫秒）作为 batch_id

2. **获取上次同步时间**
   - 从 `dws_sync_meta` 表读取每个 ODS 表的 `last_sync_time`
   - 只处理 `etl_time > last_sync_time` 的记录

3. **构建临时表**
   - 创建 ETL 临时表（如 `tmp_icp_companies`、`tmp_crm_mobiles` 等）
   - 用于高效 JOIN 操作

4. **UPSERT 数据**
   - 使用 `INSERT ... ON DUPLICATE KEY UPDATE` 更新已有记录
   - 标记 `sync_batch_id` 用于后续清理

5. **删除检测**
   - 对比源表与目标表，检测已删除的记录

6. **更新同步元数据**
   - 更新 `dws_sync_meta` 表的 `last_sync_time` 和 `status`

### 4.3 并发控制

- 使用 `asyncio.Lock()` 实现并发控制
- 同一时间只能运行一个同步任务（全量或增量）
- 如果已有同步任务运行，新的同步请求将返回 `409 Conflict`

### 4.4 重试机制

- DML 操作（INSERT/UPDATE/DELETE）支持自动重试
- 重试场景：死锁（deadlock）、锁等待超时（lock wait timeout）
- DDL 操作不支持重试（因为不是安全可重试的）

---

## 5. 错误处理

### 5.1 常见错误码

| 错误码 | 说明 |
|--------|------|
| 409 | 已有同步任务正在运行 |
| 500 | 同步执行失败（查看 error_message 获取详细信息） |

### 5.2 错误响应格式

```json
{
  "detail": "A sync run is already in progress. Please wait."
}
```

或

```json
{
  "detail": "Full sync failed: [错误信息]"
}
```

### 5.3 同步失败处理

- 同步失败时，状态更新为 `failed`
- 错误信息记录在 `dws_sync_log.error_message` 字段
- 如果使用了双表轮换，会自动回滚表轮换操作
- 建议查看后端日志获取详细错误堆栈

---

## 6. 附录

### 6.1 相关文件路径

| 文件 | 说明 |
|------|------|
| `backend/app/routers/sync.py` | 同步 API 路由定义 |
| `backend/app/services/etl_sync.py` | ETL 同步核心逻辑 |
| `scripts/build_aggregation.sql` | DWS 层建表语句 |
| `scripts/create_sync_log_table.sql` | dws_sync_log 建表语句 |

### 6.2 ODS 源表列表

全量/增量同步处理的 ODS 表（带 `_day` 后缀）：

- `ods_crm_contact_day` - CRM 联系人
- `ods_crm_opportunity_day` - CRM 商机
- `ods_zhique_contact_day` - 致趣联系人
- `ods_marketing_lead_day` - 营销线索
- `ods_zhique_behavior_list_day` - 致趣行为列表
- `ods_tianrun_session_day` - 天润会话
- `ods_linkflow_contacts_day` - LinkFlow 联系人
- `ods_linkflow_events_day` - LinkFlow 事件
- `ods_ruijie_website_user_day` - 锐捷网站用户
- `ods_tianrun_customer_profile_day` - 天润客户资料
- `ods_tianrun_session_detail_day` - 天润会话详情
- `ods_key_customer` - 重要客户表

### 6.3 DWS 目标表列表

同步构建的 DWS 表：

- `dws_contact_mapping` - 跨系统联系人映射
- `dws_interaction_detail` - 互动详情
- `dws_customer_360` - 客户 360 视图
- `dws_contact_360` - 联系人 360 视图
