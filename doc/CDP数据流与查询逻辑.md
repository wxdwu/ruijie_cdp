# CDP ABM 360 数据流与查询逻辑文档

## 一、数据总览

### ODS 数据源 (11张表)

| ODS 表 | 行数 | 说明 | 关联键 |
|---|---|---|---|
| `ods_zhique_contact_day` | 2,263 | **基准表** - 致趣联系人明细（ICP客户池） | `related_company` → 客户名 |
| `ods_crm_contact_day` | 6,650 | CRM联系人明细 | `customer_name`, `mobile` |
| `ods_crm_opportunity_day` | 51,797 | CRM商机明细 | `customer_name`, `opp_code` |
| `ods_marketing_lead_day` | 34,188 | 营销线索 | `customer_company`, `contact_phone` |
| `ods_linkflow_contacts_day` | 74,947 | Linkflow联系人 | `mobile_phone` |
| `ods_linkflow_events_day` | 14,077,180 | Linkflow事件 | `contact_id` |
| `ods_zhique_behavior_list_day` | 303,526 | 致趣行为明细 | `company_name`, `mobile_phone` |
| `ods_tianrun_session_day` | 776,937 | 天润客服会话 | `visitor_mobile_phone` |
| `ods_ruijie_website_user_day` | 130,473 | 官网用户 | `mobile_phone` |

### DWS 聚合表 (6张)

| DWS 表 | 行数 | 说明 | 主键 |
|---|---|---|---|
| `tmp_icp_customers` | 1,012 | ICP客户名单（基准过滤） | `customer_name` |
| `dws_customer_360` | 1,012 | 客户360主表 | `id` + `customer_name` |
| `dws_contact_mapping` | 122,967 | 联系人映射表 | `id` + `customer_name` |
| `dws_contact_360` | 120,235 | 联系人聚合表 | `id` + `customer_id` |
| `dws_interaction_detail` | 22,931 | 互动行为明细表 | `id` + `source_id` |
| `dws_sync_meta` | 10 | ETL同步状态表 | `table_name` |

---

## 二、ETL 数据构建流程

### 整体架构图

```
                    ┌─────────────────────┐
                    │ tmp_icp_customers   │ 1012 ICP客户
                    │ (基准过滤表)         │ related_company FROM ods_zhique_contact_day
                    └──────────┬──────────┘
                               │ 作为锚点
                    ┌──────────▼──────────┐
          Step 0:  │  建立ICP客户过滤条件  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
Step 1: 联系人映射 │ dws_contact_mapping │ 122,967行
                    └──────────┬──────────┘
              ┌───────────────┼───────────────┐
              │               │               │
    a. 致趣联系人      b. CRM联系人(匹配)    c. 营销线索      d. Linkflow联系人      e. 天润会话
    (2,390行)       (按客户名/手机号过滤)   (按客户公司过滤)  (按手机号匹配)        (按客户名匹配)
       │               │                     │                 │                     │
       ▼               ▼                     ▼                 ▼                     ▼
    INSERT          INSERT                INSERT            INSERT                INSERT
  related_company  customer_name        customer_company   mobile_phone          customer_name
  ──────────►      ──────────►           ──────────►        ──────────►           ──────────►
  customer_name    customer_name         customer_name      customer_name         customer_name

                    ┌──────────▼──────────┐
Step 2: 互动行为    │dws_interaction_detail│ 22,931行
                    └──────────┬──────────┘
              ┌───────────────┼───────────────┐
              │               │               │
    a. 致趣行为         b. 天润会话         c. Linkflow事件
    (4,744行)           (10,000行)          (8,187行)
    company_name        customer_name       contact_id
    ──────────►         ──────────►         ──────────►
    customer_name       customer_name       customer_name
    (仅ICP客户)         (仅ICP客户)         (仅ICP客户)

                    ┌──────────▼──────────┐
Step 3: 客户360     │ dws_customer_360   │ 1,012行
                    └──────────┬──────────┘
              ┌───────────────┼───────────────┐
              │               │               │
    Phase 1: 互动聚合    Phase 2: CRM enrich   Phase 3: CRM商机
    (LEFT JOIN)         (LEFT JOIN)           (LEFT JOIN)
    dws_interaction     dws_contact_mapping   ods_crm_opportunity
    ──────────►         ──────────►           ──────────►
    COUNT, SUM          industry,             purchase_stage,
    MAX                 owner_name            forecast_type,
                        role_coverage         active_opp_amount

                    ┌──────────▼──────────┐
Step 4: 联系人360   │ dws_contact_360    │ 120,235行
                    └─────────────────────┘
    LEFT JOIN dws_interaction_detail (按contact_name, mobile)
    → interaction_count, last_interaction_time
```

### 各步骤详细逻辑

#### Step 1: 联系人映射 (dws_contact_mapping)

**数据来源顺序**（优先级从高到低）：

| 顺序 | 来源表 | 匹配条件 | 行数 |
|---|---|---|---|
| a | `ods_zhique_contact_day` | `related_company IS NOT NULL` | 2,390 |
| b | `ods_crm_contact_day` | `customer_name IN (tmp_icp)` OR `mobile IN (tmp_icp)` | 2,938 |
| c | `ods_marketing_lead_day` | `customer_company IN (tmp_icp)` OR `contact_phone IN (tmp_icp)` | 32,961 |
| d | `ods_linkflow_contacts_day` | `mobile_phone IN (所有联系人mobile)` | 101 |
| e | `ods_tianrun_session_day` | `customer_name IN (tmp_icp)` | 84,577 |

**关键逻辑**：
- 使用 `INSERT IGNORE` 避免重复插入
- 以 `customer_name` 为主键进行去重
- 记录 `source_table` 标识数据来源

#### Step 2: 互动行为 (dws_interaction_detail)

**数据来源**：

| 来源 | 匹配条件 | 过滤逻辑 | 行数 |
|---|---|---|---|
| 致趣行为 | `company_name IN (tmp_icp_customers)` | 仅 ICP 客户的互动 | 4,744 |
| 天润会话 | `customer_name IN (tmp_icp_customers)` | 仅 ICP 客户的会话 | 10,000 |
| Linkflow事件 | `contact_id IN (linkflow接触点)` | 仅已关联联系人的事件 | 8,187 |

**字段映射**：

| dws_interaction_detail | 致趣 | 天润 | Linkflow |
|---|---|---|---|
| customer_name | company_name | customer_name | (通过contact_id→mobile→customer_name) |
| contact_name | contact_name | visitor_name | (NULL) |
| mobile | mobile_phone | visitor_mobile_phone | (NULL) |
| channel | behavior_type→channel | contact_type_name→'客服' | event_name→channel |
| behavior_type | behavior_type | - | event_name |
| content | behavior_name | - | event_name |
| event_time | behavior_time | FROM_UNIXTIME(start_time_sec) | FROM_UNIXTIME(event_date_ms/1000) |

#### Step 3: 客户360主表 (dws_customer_360)

**Phase 1 - 互动聚合**：
```sql
INSERT INTO dws_customer_360
SELECT 
  icp.customer_name,
  COUNT(i.id) AS interaction_count_total,
  SUM(CASE WHEN i.event_time >= NOW()-INTERVAL 30 DAY THEN 1 ELSE 0 END) AS interaction_count_30d,
  MAX(i.event_time) AS last_interaction_time,
  ...
FROM tmp_icp_customers icp
LEFT JOIN dws_interaction_detail i 
  ON i.customer_name = icp.customer_name
GROUP BY icp.customer_name
```

**Phase 2 - CRM联系人属性**：
```sql
UPDATE dws_customer_360 c360
INNER JOIN (
  SELECT customer_name,
    MAX(industry) AS industry,
    MAX(ruijie_region) AS region,
    MAX(sales_name) AS owner_name,
    COUNT(DISTINCT contact_name) AS contact_count,
    COUNT(DISTINCT mobile) AS mobile_count
  FROM ods_crm_contact_day
  GROUP BY customer_name
) crm ON crm.customer_name = c360.customer_name
SET c360.industry = crm.industry,
    c360.owner_name = crm.owner_name, ...
```

**Phase 3 - CRM商机属性**：
```sql
UPDATE dws_customer_360 c360
INNER JOIN (
  SELECT customer_name,
    MAX(customer_stage) AS purchase_stage,
    MAX(forecast_type) AS forecast_type,
    COUNT(CASE WHEN is_active=1 THEN 1 END) AS active_opp_count,
    SUM(CASE WHEN is_active=1 THEN amount_10k ELSE 0 END) AS active_opp_amount,
    COUNT(CASE WHEN is_funnel='是' THEN 1 END) AS funnel_opp_count,
    SUM(actual_order_amount_10k) AS won_amount
  FROM ods_crm_opportunity_day
  GROUP BY customer_name
) opp ON opp.customer_name = c360.customer_name
SET ...
```

#### Step 4: 联系人360 (dws_contact_360)

```sql
INSERT INTO dws_contact_360
SELECT 
  c360.id AS customer_id,
  cm.contact_name, cm.mobile, cm.email, ...
  COALESCE(agg.interaction_count, 0),
  agg.last_interaction_time,
  ...
FROM dws_contact_mapping cm
LEFT JOIN dws_customer_360 c360 ON c360.customer_name = cm.customer_name
LEFT JOIN (
  SELECT contact_name, mobile,
    COUNT(*) AS interaction_count,
    MAX(event_time) AS last_interaction_time
  FROM dws_interaction_detail
  GROUP BY contact_name, mobile
) agg ON agg.contact_name = cm.contact_name AND agg.mobile = cm.mobile
```

---

## 三、API 查询逻辑

### 客户列表 API
```
GET /api/customers
→ SELECT * FROM dws_customer_360 WHERE 1=1 [filters]
  ORDER BY intent_score DESC LIMIT :limit OFFSET :offset
```

### 客户详情 API
```
GET /api/customers/{id}
→ SELECT * FROM dws_customer_360 WHERE id = :id

GET /api/customers/{id}/contacts
→ SELECT * FROM dws_contact_360 WHERE customer_id = :id
  ORDER BY interaction_count DESC

GET /api/customers/{id}/interactions
→ SELECT * FROM dws_interaction_detail 
  WHERE customer_name = (SELECT customer_name FROM dws_customer_360 WHERE id = :id)
  ORDER BY event_time DESC LIMIT :limit

GET /api/customers/{id}/opportunities
→ SELECT * FROM ods_crm_opportunity_day WHERE customer_name = (SELECT customer_name FROM dws_customer_360 WHERE id = :id)
```

---

## 四、关键关联关系图

```
ods_zhique_contact_day.related_company (2,263行, 1,012去重)
        │
        ▼ (去重后)
tmp_icp_customers.customer_name (1,012行)
        │
        ├────► dws_customer_360 (1,012行) ──── API: 客户列表/详情
        │         │
        │         ├── customer_name ───► ods_crm_opportunity_day (商机 enrich)
        │         ├── customer_name ───► ods_crm_contact_day (联系人 enrich)
        │         └── id ───► dws_contact_360 (联系人聚合)
        │
        ├────► dws_contact_mapping (122,967行)
        │         │
        │         ├── mobile_phone ───► ods_linkflow_contacts_day (匹配)
        │         ├── customer_name ───► ods_marketing_lead_day (匹配)
        │         └── customer_name ───► ods_tianrun_session_day (匹配)
        │
        └────► dws_interaction_detail (22,931行) ──── API: 互动时间线
                  │
                  ├── company_name ───► ods_zhique_behavior_list_day (4,744行)
                  ├── customer_name ───► ods_tianrun_session_day (10,000行)
                  └── contact_id ─────► ods_linkflow_events_day (8,187行)
```

---

## 五、事件数据流转

```
原始事件表 (27M+)                          聚合后的互动明细
┌─────────────────────────────┐           ┌──────────────────────────┐
│ ods_zhique_behavior_list    │ 303,526   │                          │
│ └─ company_name IN tmp_icp  │ ────────► │ dws_interaction_detail   │
│   → 4,744 条有效记录        │           │ └─ customer_name         │
├─────────────────────────────┤           │ └─ contact_name          │
│ ods_tianrun_session_day     │ 776,937   │ └─ mobile                │
│ └─ customer_name IN tmp_icp │ ────────► │ └─ channel               │
│   → 10,000 条有效记录       │           │ └─ behavior_type         │
├─────────────────────────────┤           │ └─ content               │
│ ods_linkflow_events_day     │ 14,077,180│ └─ event_time            │
│ └─ contact_id IN linkflow  │ ────────► │ └─ is_high_value         │
│   → 8,187 条有效记录        │           │ └─ source_id (去重用)    │
└─────────────────────────────┘           │                          │
                                          │ 总计: 22,931 行          │
                                          └──────────────────────────┘
```