# ODS 聚合 DWS 逻辑说明

> 本文梳理 CDP 数仓中 **ODS → DWS** 的聚合链路，聚焦以下 4 张 DWS 表：
> `dws_contact_mapping`、`dws_interaction_detail`、`dws_customer_360`、`dws_contact_360`。
> 逐表说明：以哪些 ODS 表为数据源、通过哪些字段映射/关联/聚合而成、过滤规则与依赖关系。
>
> 代码位置：`backend/app/services/etl_sync.py`（全量：`run_full_sync`；增量：`run_incremental_sync`）。
> 表结构参考：`backup/backup20260710/app_cdp_struc.sql`。

---

## 0. 总体架构与依赖关系

### 0.1 ICP 锚点表（关键前置）

所有 DWS 聚合都以 **ICP 客户白名单** 为基准，只有命中白名单的客户/联系人才会进入 360 层。

| 临时锚点表 | 来源 ODS | 取值字段 | 说明 |
|---|---|---|---|
| `tmp_icp_customers` | `ods_zhique_contact_day` | `DISTINCT related_company` | ICP 客户公司名白名单（唯一锚点） |
| `tmp_icp_mobiles` | `ods_zhique_contact_day` | `DISTINCT mobile` | ICP 客户手机号白名单 |

> 代码：`_build_icp_customers_table`（约 341 行）、`_build_tmp_icp_filters`（约 469 行）。
> 规则：**能进入 `dws_customer_360` / `dws_contact_360` 的公司/联系人，其公司名必须存在于 `tmp_icp_customers`。**

### 0.2 构建顺序（全量 `run_full_sync`）

```
Step 4  构建 ICP 锚点 (tmp_icp_customers / tmp_icp_mobiles)
Step 6  dws_contact_mapping   ← 5 个联系人源（明细宽表）
Step 7  dws_interaction_detail ← 5 个互动源（明细事实表）
Step 8  dws_customer_360      ← interaction_detail + CRM 聚合 + ICP 锚点
Step 9  dws_contact_360       ← contact_mapping + interaction_detail + customer_360
```

四张表之间的依赖：

```
ODS 联系人源 ──► dws_contact_mapping ──┐
                                       ├──► dws_customer_360 ──► dws_contact_360
ODS 互动源  ──► dws_interaction_detail ┘         ▲                     ▲
                                                 └── tmp_icp_customers ─┘
```

### 0.3 中间聚合临时表

| 临时表 | 来源 ODS | 聚合键 | 用途 |
|---|---|---|---|
| `tmp_crm_mobiles` | `ods_crm_contact_day` | `DISTINCT mobile` | 驱动致趣行为的手机号匹配 |
| `tmp_valid_linkflow_contacts` | `ods_linkflow_contacts_day` ⋈ `ods_crm_contact_day`（mobile 关联） | `contact_id` | Linkflow 联系人补齐 `customer_name` |
| `tmp_crm_contact_attr` | `ods_crm_contact_day` | `GROUP BY customer_name` | 客户级 CRM 属性（行业/区域/负责人/联系人数） |
| `tmp_crm_opportunity_agg` | `ods_crm_opportunity_day` | `GROUP BY customer_name` | 客户级商机指标（活跃商机数/金额/赢单额） |
| `tmp_contact_interactions` | `dws_interaction_detail` | `GROUP BY contact_name, mobile` | 联系人级互动次数聚合 |

---

## 1. dws_contact_mapping（联系人映射明细宽表）

### 1.1 定位

联系人层的**明细宽表**（非聚合），把 5 个来源系统的联系人「纵向 UNION」合并到一张表，保留全部联系人（含非 ICP）作为明细源。写入方式：`TRUNCATE` 后按来源逐段 `INSERT IGNORE`。

> 代码：`_load_contact_mapping`（约 603 行）。唯一键 `uk_customer_mobile(customer_name, mobile)`。

### 1.2 数据源与字段映射

| 来源(source_table) | 来源 ODS 表 | customer_name | contact_name | mobile | 其他字段 | 过滤/关联条件 |
|---|---|---|---|---|---|---|
| `zhique`（锚点） | `ods_zhique_contact_day` | `related_company` | `contact_name` | `mobile` | `email`,`department`,`position` | `related_company` 非空 |
| `crm` | `ods_crm_contact_day` | `customer_name` | `contact_name` | `mobile` | `email`,`department`,`position`,`purchase_role`,`role_category`(由 `purchase_role` 经 `ROLE_MAP` 映射) | `customer_name` 非空 **且**（`customer_name ∈ tmp_icp_customers` **或** `mobile ∈ tmp_icp_mobiles`） |
| `marketing` | `ods_marketing_lead_day` | `COALESCE(final_company_name, customer_company, opp_customer_name)` | `customer_name` | `contact_phone` | `email`,`position`←`lead_function` | 上述 COALESCE 公司名非空，`DISTINCT` 去重 |
| `linkflow` | `tmp_valid_linkflow_contacts` ⋈ `ods_linkflow_contacts_day` | `lc.customer_name`（由 CRM mobile 关联补齐） | `lc.name` | `lc.mobile_phone` | `email`,`linkflow_contact_id`←`contact_id` | 经 `contact_id` 内连 linkflow 明细 |
| `tianrun` | `ods_tianrun_session_day` | `customer_name`（渠道/地域标签，低质量） | `visitor_name` | 无 | — | `customer_name`、`visitor_name` 均非空，`DISTINCT` |

### 1.3 关键映射规则

- `role_category`：CRM 的 `purchase_role` 通过 `ROLE_MAP` 转换（拍板者/决策者→决策者；评估者→技术评估者；使用者→使用者；其他→其他），无匹配为 `未知`。
- CRM 联系人做了 ICP 收敛（公司名或手机号命中白名单），其余来源保留全部明细。
- Linkflow 联系人自身无公司名，靠 `mobile_phone = CRM.mobile` 关联补齐 `customer_name`。

---

## 2. dws_interaction_detail（互动明细事实表）

### 2.1 定位

互动层的**明细事实表**（一行 = 一次互动事件），把 5 个互动来源「纵向合并」。写入方式：`TRUNCATE` 后按来源逐段 `INSERT IGNORE`，靠唯一键 `uk_source_id(source_table, source_id)` 去重。

> 代码：`_load_interaction_detail`（约 910 行），调用 5 个 loader。

### 2.2 数据源与字段映射

| source_table | 来源 ODS 表 | customer_name | contact_name | mobile | channel | behavior_type | content | event_time | source_id | 关联/过滤 |
|---|---|---|---|---|---|---|---|---|---|---|
| `zhique` | `ods_zhique_behavior_list_day` b | `cm.customer_name`（经 CRM 关联） | `b.contact_name` | `b.mobile_phone` | `behavior_type` 经 `ZHIQUE_CHANNEL_MAP` | `b.behavior_type` | `b.behavior_name` | `b.behavior_time` | `b.behavior_id` | `b.mobile_phone` 同时命中 `tmp_crm_mobiles` 与 `ods_crm_contact_day.mobile`（内连接补公司名） |
| `tianrun` | `ods_tianrun_session_day` s | `s.customer_name` | `s.visitor_name` | 无(NULL) | `contact_type_name`→web/wechat | `receive_type_name`(默认 online_chat) | `close_reason_name` | `FROM_UNIXTIME(start_time_sec)` | `s.id` | **`INNER JOIN tmp_icp_customers`**（过滤地域/访客标签），`customer_name`、`visitor_name` 非空；`is_high_value`=时长>60s |
| `linkflow` | `ods_linkflow_events_day` e | `lc.customer_name` | `lc.name` | `lc.mobile_phone` | 固定 `web` | `e.event_name` | — | `FROM_UNIXTIME(event_date_ms/1000)` | `e.event_id` | 经 `tmp_valid_linkflow_contacts.contact_id` 内连 |
| `crm_lead` | `ods_crm_lead_data_day` l | `客户单位` | `客户姓名` | `联系电话` | `线索来源大类`(默认 crm) | 固定 `线索` | `COALESCE(活动名称, 线索来源类型)` | `线索获得日期` | `MD5(线索编号+客户单位+客户姓名+联系电话+线索获得日期+活动名称)` 前 15 位转 bigint | `客户单位` 非空 **且** `线索获得日期` 非空 |
| `crm_opportunity` | `ods_crm_opportunity_data_day` o | `客户名` | `业务机会所有人名称` | 无(NULL) | `商机来源`(默认 crm) | 固定 `商机` | `业务机会名称` | `创建日期-转化` | `MD5(业务机会编码+客户名+业务机会名称+创建日期-转化+商机来源)` 前 15 位转 bigint | `客户名` 非空 **且** `创建日期-转化` 非空 |

### 2.3 关键映射规则

- 致趣渠道 `ZHIQUE_CHANNEL_MAP`：打开邮件/点击邮件链接→email；报名会议/参会/观看直播→event；下载资料/表单提交/访问落地页→web。
- 天润会话 `customer_name` 是「地域/访客标签」（如"江苏徐州xxx"），非真实公司名，故用 `INNER JOIN tmp_icp_customers` 过滤，避免污染下游客户维度。
- CRM 线索/商机无稳定源主键，用行内容 `MD5` 哈希构造 `source_id` 去重；线索/商机各视为一次客户交互。

---

## 3. dws_customer_360（客户 360 聚合表）

### 3.1 定位

客户层的**聚合宽表**（一行 = 一个 ICP 客户），以 `tmp_icp_customers` 为主表（锚点），左连 `dws_interaction_detail` 聚合互动指标，再多阶段 `UPDATE` 富化 CRM/商机/重客属性。

> 代码：`_build_customer_360`（约 937 行）。唯一键 `uk_customer_name(customer_name)`。

### 3.2 构建阶段与字段来源

**Phase 1 — 互动聚合（主表 `tmp_icp_customers` LEFT JOIN `dws_interaction_detail`，`GROUP BY icp.customer_name`）**

| 目标字段 | 聚合逻辑 |
|---|---|
| `interaction_count_total` | `COUNT(i.id)` |
| `interaction_count_30d` | `SUM(event_time ≥ NOW()-30d)` |
| `last_interaction_time` | `MAX(i.event_time)` |
| `last_interaction_channel` | `GROUP_CONCAT(DISTINCT channel)` 取第一个 |
| `top_channels` | `DISTINCT channel` 组成 JSON 数组 |

**Phase 2 — CRM 联系人属性（INNER JOIN `tmp_crm_contact_attr`，源 `ods_crm_contact_day`）**

| 目标字段 | 来源 |
|---|---|
| `industry` | `MAX(industry)` |
| `region` | `MAX(ruijie_region)` |
| `owner_name` | `MAX(sales_name)` |
| `attribute` | `MAX(attribute)` |
| `contact_count` | `COUNT(DISTINCT contact_name)` |
| `mobile_count` | `COUNT(DISTINCT mobile)` |

**Phase 3 — CRM 商机指标（INNER JOIN `tmp_crm_opportunity_agg`，源 `ods_crm_opportunity_day`）**

| 目标字段 | 来源 |
|---|---|
| `purchase_stage` | `MAX(customer_stage)` |
| `forecast_type` | `MAX(forecast_type)` |
| `active_opp_count` | `COUNT(is_active=1)` |
| `active_opp_amount` | `SUM(is_active=1 时 amount_10k*10000)` |
| `funnel_opp_count` | `COUNT(is_funnel='是')` |
| `won_amount` | `SUM(actual_order_amount_10k*10000)` |

**Phase 4 — 派生字段（源 `dws_contact_mapping` + 本表已有值）**

| 目标字段 | 逻辑 |
|---|---|
| `role_coverage` | 按 `dws_contact_mapping.role_category` 分组：三类齐全→全；有部分→部分；否则→无 |
| `source_tables` | `dws_contact_mapping.source_table` 去重 JSON 数组 |
| `data_coverage` | JSON：has_crm/has_opp/has_contacts/has_interactions |
| `intent_score` | `LEAST(100, 30d互动×2 + 有活跃商机20 + 联系人数加权)` |
| `intent_level` | 30d≥10且有商机→高；30d≥3→中；有互动→低；否则→无 |

**Phase 5 — 重要客户富化（源 `ods_key_customer`）**

- 按 `key_customer_name = customer_name` `UPDATE`：`owner_name←customer_name`、`region←department_level3`、`industry←industry_category`、`attribute←attribute`。
- 白名单外的重客用 `INSERT IGNORE` 新增行。

### 3.3 主表与聚合键

- **主表**：`tmp_icp_customers`（保证只有 ICP 客户成行）。
- **聚合键**：`customer_name`（跨 `dws_interaction_detail`、CRM 聚合临时表、`dws_contact_mapping` 均以此关联）。

---

## 4. dws_contact_360（联系人 360 聚合表）

### 4.1 定位

联系人层的**聚合宽表**（一行 = 一个联系人），以 `dws_contact_mapping` 为主表，关联联系人级互动聚合 `tmp_contact_interactions`，并挂接到 `dws_customer_360` 取得 `customer_id`。

> 代码：`_build_contact_360`（约 1129 行）。唯一键 `uk_customer_mobile(customer_id, mobile)`。

### 4.2 前置聚合：tmp_contact_interactions

以 `dws_interaction_detail` 为源，`GROUP BY contact_name, mobile`：

| 目标字段 | 聚合逻辑 |
|---|---|
| `interaction_count` | `COUNT(*)` |
| `interaction_count_30d` | `SUM(event_time ≥ NOW()-30d)` |
| `last_interaction_time` | `MAX(event_time)` |

### 4.3 字段来源与关联

主查询：`dws_contact_mapping cm` **INNER JOIN** `tmp_icp_customers icp`（公司名白名单）**LEFT JOIN** `dws_customer_360 c360`（取 `customer_id`）**LEFT JOIN** `tmp_contact_interactions agg`（互动聚合）。

| 目标字段 | 来源 |
|---|---|
| `customer_id` | `dws_customer_360.id`（按 `customer_name` 关联） |
| `contact_name`,`mobile`,`email`,`department`,`position`,`purchase_role`,`role_category` | `dws_contact_mapping` 对应列 |
| `interaction_count`,`interaction_count_30d`,`last_interaction_time` | `tmp_contact_interactions`（按 `contact_name` + `mobile` 关联，mobile 用 `<=>` NULL 安全比较） |
| `source_tables` | `dws_contact_mapping.source_table` 单元素 JSON |
| `linkflow_contact_id` | `dws_contact_mapping.linkflow_contact_id` |
| `activity_level` | 二次 `UPDATE`：30d≥10→high；≥3→medium；有互动→low；否则→none |

### 4.4 关键过滤规则（孤儿联系人剔除）

- **`INNER JOIN tmp_icp_customers icp ON icp.customer_name = cm.customer_name`**：只保留公司名在 ICP 白名单内的联系人。
- **`WHERE c360.id IS NOT NULL AND c360.id != 0`**：双保险，剔除 `customer_id=0/NULL` 的孤儿联系人。
- 即：能进入 `dws_contact_360` 的联系人，其公司必须已存在于 `dws_customer_360`（有合法非零 `customer_id`）。

---

## 5. 汇总对照表

| DWS 表 | 层级 | 类型 | 主表/主源 | 主要聚合/关联键 | 主要 ODS 来源 |
|---|---|---|---|---|---|
| `dws_contact_mapping` | 联系人 | 明细宽表(UNION) | 逐来源 INSERT | `customer_name`,`mobile` | zhique_contact / crm_contact / marketing_lead / linkflow_contacts / tianrun_session |
| `dws_interaction_detail` | 互动 | 明细事实表(UNION) | 逐来源 INSERT | `source_table`,`source_id` | zhique_behavior / tianrun_session / linkflow_events / crm_lead / crm_opportunity |
| `dws_customer_360` | 客户 | 聚合宽表 | `tmp_icp_customers` | `customer_name` | interaction_detail + crm_contact + crm_opportunity + key_customer |
| `dws_contact_360` | 联系人 | 聚合宽表 | `dws_contact_mapping` | `customer_id`+`mobile`；`contact_name`+`mobile` | contact_mapping + interaction_detail + customer_360 |

> 说明：全量与增量共用同一套聚合函数（增量通过 `*_temp` 基表参数化调用相同逻辑），因此上述映射对两种模式一致。
