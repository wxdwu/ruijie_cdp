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

#### ODS 表原始字段与抽取逻辑

##### 1. ods_zhique_contact_day (基准表 - 致趣联系人)

**作用**：提供 ICP 客户名单（1,012个去重客户，2,263行联系人记录）

**原始字段**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| related_company | varchar(255) | 关联公司名称（客户名） |
| contact_name | varchar(64) | 联系人姓名 |
| mobile | varchar(32) | 手机号 |
| email | varchar(128) | 邮箱 |
| department | varchar(128) | 部门 |
| position | varchar(128) | 职务 |
| industry | varchar(64) | 行业 |
| ruijie_region | varchar(64) | 锐捷区域 |
| attribute | varchar(32) | 属性 (H/M/L) |

**抽取SQL**：
```sql
-- 建ICP客户过滤表
CREATE TABLE tmp_icp_customers AS
SELECT DISTINCT related_company as customer_name
FROM ods_zhique_contact_day
WHERE related_company IS NOT NULL AND related_company != ''
```

**抽取结果**：1,012 个唯一客户名

---

##### 2. ods_zhique_behavior_list_day (致趣行为)

**作用**：提供互动行为数据（致趣渠道的邮件打开、直播参与、资料下载等）

**原始字段**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| contact_name | varchar(255) | 联系人姓名 |
| mobile_phone | varchar(64) | 手机号 |
| email | varchar(255) | 邮箱 |
| company_name | varchar(255) | 公司名称 |
| behavior_type | varchar(255) | 行为类型（打开邮件/下载资料/报名会议等） |
| behavior_name | varchar(255) | 行为名称/内容标题 |
| behavior_time | datetime | 行为时间 |

**抽取SQL**：
```sql
SELECT company_name, contact_name, mobile_phone, email,
       behavior_type, behavior_name, behavior_time, id as source_id
FROM ods_zhique_behavior_list_day
WHERE company_name IN (SELECT customer_name FROM tmp_icp_customers)
```

**过滤条件**：仅保留 `company_name` 在 ICP 客户名单中的记录
**抽取结果**：4,744 行互动记录

---

##### 3. ods_crm_contact_day (CRM联系人)

**作用**：补充 CRM 系统中的联系人信息（销售姓名、采购角色、行业等）

**原始字段**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| customer_name | varchar(255) | 客户名称 |
| contact_name | varchar(64) | 联系人姓名 |
| mobile | varchar(32) | 手机号 |
| email | varchar(128) | 电子邮件 |
| department | varchar(128) | 部门 |
| position | varchar(128) | 职务 |
| purchase_role | varchar(64) | 采购角色（拍板者/决策者/评估者等） |
| industry | varchar(64) | 行业归属 |
| sales_name | varchar(64) | 销售姓名（负责人） |
| ruijie_region | varchar(128) | 锐捷区域 |
| attribute | varchar(32) | 属性 |

**抽取SQL**：
```sql
SELECT customer_name, contact_name, mobile, email,
       department, position, purchase_role, industry,
       sales_name, ruijie_region, attribute
FROM ods_crm_contact_day
WHERE customer_name IN (SELECT customer_name FROM tmp_icp_customers)
   OR mobile IN (SELECT mobile FROM tmp_icp_customers)
```

**过滤条件**：`customer_name` 匹配 ICP 客户 **或** `mobile` 匹配 ICP 客户联系人手机号
**抽取结果**：2,938 行（去重后）

---

##### 4. ods_crm_opportunity_day (CRM商机)

**作用**：提供商机数据（采购阶段、商机金额、预测类别等）

**原始字段**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| customer_name | varchar(255) | 客户名称 |
| opp_name | varchar(500) | 业务机会名称 |
| opp_code | varchar(64) | 业务机会编码 |
| customer_stage | varchar(64) | 客户进入阶段 |
| forecast_type | varchar(32) | 预测类别（线索/机会/可能/优势/确保） |
| amount_10k | decimal(20,4) | 金额(万元) |
| win_rate | decimal(5,2) | 赢率(%) |
| actual_order_amount_10k | decimal(20,4) | 实际下单金额(万元) |
| is_funnel | varchar(16) | 是否进入漏斗 |
| is_cancel_lost | varchar(16) | 是否取消/丢单 |
| is_active | tinyint | 是否活动中 |
| industry | varchar(64) | 行业归属 |
| owner_name | varchar(64) | 业务机会所有人 |
| region | varchar(64) | 大区 |

**抽取SQL**（在客户360构建时直接使用，不单独抽取到DWS）：
```sql
SELECT customer_name, customer_stage, forecast_type, amount_10k,
       win_rate, actual_order_amount_10k, is_funnel, is_cancel_lost,
       is_active, industry, owner_name, region
FROM ods_crm_opportunity_day
WHERE customer_name IN (SELECT customer_name FROM tmp_icp_customers)
```

**过滤条件**：`customer_name` 匹配 ICP 客户名单
**抽取结果**：约 5,000 行（51,797 中匹配 ICP 的部分）

---

##### 5. ods_marketing_lead_day (营销线索)

**作用**：补充营销渠道联系人信息

**原始字段**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| customer_company | varchar(500) | 客户单位 |
| final_company_name | varchar(500) | 最终公司名称 |
| customer_name | varchar(255) | 客户姓名 |
| contact_phone | varchar(64) | 联系电话 |
| email | varchar(255) | 邮箱 |
| industry | varchar(128) | 行业 |
| province | varchar(64) | 省份 |
| product_line | varchar(255) | 产品线 |

**抽取SQL**：
```sql
SELECT customer_company, final_company_name, customer_name,
       contact_phone, email, industry, province, product_line
FROM ods_marketing_lead_day
WHERE customer_company IN (SELECT customer_name FROM tmp_icp_customers)
   OR contact_phone IN (SELECT mobile FROM tmp_icp_customers)
```

**过滤条件**：客户单位匹配 ICP 客户 **或** 联系电话匹配 ICP 联系人手机
**抽取结果**：32,961 行

---

##### 6. ods_linkflow_contacts_day + ods_linkflow_events_day (Linkflow)

**作用**：提供官网/营销活动互动数据

**Linkflow 联系人**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| contact_id | bigint | 联系人ID（事件关联用） |
| name | varchar(255) | 联系人姓名 |
| mobile_phone | varchar(64) | 手机号 |
| email | varchar(255) | 邮箱 |
| company | varchar(255) | 公司 |

**Linkflow 事件**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| contact_id | bigint | 联系人ID（关联联系人表） |
| event_name | varchar(255) | 事件名称（WEBSITE__PAGE_VIEW等） |
| event_date_ms | bigint | 事件发生时间戳（毫秒） |

**抽取SQL**：
```sql
-- 先通过手机号找到匹配ICP客户的Linkflow联系人
SELECT contact_id, name, mobile_phone, email, company
FROM ods_linkflow_contacts_day
WHERE mobile_phone IN (
  SELECT DISTINCT mobile FROM dws_contact_mapping WHERE mobile IS NOT NULL
)

-- 再通过这些 contact_id 抽取事件
SELECT id, contact_id, event_name, event_date_ms
FROM ods_linkflow_events_day
WHERE contact_id IN (上述匹配到的 contact_id 列表)
```

**过滤条件**：`mobile_phone` 匹配已导入联系人的手机号 → 获取 `contact_id` → 过滤事件
**抽取结果**：101 行联系人 + 8,187 行事件

---

##### 7. ods_tianrun_session_day (天润客服会话)

**作用**：提供在线客服互动数据

**原始字段**：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 自增主键 |
| customer_name | varchar(255) | 客户名称 |
| visitor_name | varchar(255) | 访客姓名 |
| visitor_mobile_phone | varchar(128) | 访客手机号 |
| visitor_email | varchar(255) | 访客邮箱 |
| contact_type_name | varchar(255) | 渠道类型 |
| start_time_sec | bigint | 会话开始时间戳（秒） |
| end_time_sec | bigint | 会话结束时间戳（秒） |
| total_duration | bigint | 会话时长（秒） |
| total_duration_pretty | varchar(64) | 会话时长（格式化） |
| province | varchar(128) | 省份 |

**抽取SQL**：
```sql
SELECT customer_name, visitor_name, visitor_mobile_phone, visitor_email,
       contact_type_name, start_time_sec, total_duration, total_duration_pretty
FROM ods_tianrun_session_day
WHERE customer_name IN (SELECT customer_name FROM tmp_icp_customers)
```

**过滤条件**：`customer_name` 匹配 ICP 客户名单
**抽取结果**：10,000 行（从 776,937 行中筛选）

---

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

**数据来源与字段映射**：

| dws字段 | 致趣行为映射 | 天润会话映射 | Linkflow事件映射 |
|---|---|---|---|
| customer_name | `company_name` | `customer_name` | 通过contact_id→mobile→customer_name |
| contact_name | `contact_name` | `visitor_name` | NULL |
| mobile | `mobile_phone` | `visitor_mobile_phone` | NULL |
| source_table | 'zhique' | 'tianrun' | 'linkflow' |
| channel | behavior_type→channel映射 | '客服' | event_name→channel映射 |
| behavior_type | `behavior_type` | `contact_type_name` | `event_name` |
| content | `behavior_name` | '会话: duration' | `event_name` |
| event_time | `behavior_time` | FROM_UNIXTIME(start_time_sec) | FROM_UNIXTIME(event_date_ms/1000) |
| is_high_value | 表单/咨询/留资=1 | 0 | 表单提交=1 |
| source_id | ODS行id | ODS行id | ODS行id（用于去重） |

**channel 映射规则**：
```
打开邮件/点击邮件链接 → email
观看直播/报名会议/参会 → event
访问落地页/下载资料 → web
```

**过滤逻辑**：
1. 致趣行为：`company_name IN tmp_icp_customers` → 4,744行
2. 天润会话：`customer_name IN tmp_icp_customers` → 10,000行
3. Linkflow事件：`contact_id IN 已匹配联系人contact_id` → 8,187行

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