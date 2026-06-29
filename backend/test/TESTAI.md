# CDP SQLBot AI 对话测试用例

> 用于测试 SQLBot Text-to-SQL AI 对话能力，覆盖简单到复杂的查询场景。
> 数据库：MySQL `app_cdp`，核心表包括 dws_customer_360、dws_contact_360、dws_interaction_detail、ods_crm_opportunity_day 等。

---

## 一、基础查询（20题）

### 1.1 单表全量查询

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 1 | 列出所有客户的基本信息 | `SELECT * FROM dws_customer_360 LIMIT`，识别"客户"=customer_name |
| 2 | 查看所有商机记录 | `SELECT * FROM ods_crm_opportunity_day`，识别"商机"=opportunity |
| 3 | 显示全部联系人的姓名和手机号 | `SELECT contact_name, mobile FROM dws_contact_360` |
| 4 | 查一下互动明细表里有什么 | `SELECT * FROM dws_interaction_detail LIMIT 20` |
| 5 | 帮我看看有哪些行业 | `SELECT DISTINCT industry FROM dws_customer_360` |

### 1.2 单条件筛选

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 6 | 企业行业有哪些客户 | `WHERE industry = '企业'`，"行业"→industry |
| 7 | 华北区域的客户都有谁 | `WHERE region = '华北'`，"区域"→region |
| 8 | 查询所有黑马客户 | `WHERE attribute = 'H'`，"黑马客户"→attribute='H' |
| 9 | 何源负责哪些客户 | `WHERE owner_name = '何源'`，"负责人"→owner_name |
| 10 | 有过通过邮件互动的客户 | `WHERE last_interaction_channel = 'email'`，"邮件"→email |

### 1.3 排序与限制

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 11 | 意向分数最高的10个客户是哪些 | `ORDER BY intent_score DESC LIMIT 10` |
| 12 | 哪些客户近30天互动最少 | `ORDER BY interaction_count_30d ASC` |
| 13 | 在途商机金额最高的前20个客户排名 | `WHERE active_opp_amount > 0 ORDER BY active_opp_amount DESC LIMIT 20` |
| 14 | 历史成交金额最多的客户 | `ORDER BY won_amount DESC`，"历史成交金额"→won_amount |
| 15 | 最近创建的商机有哪些，按时间倒序 | `ORDER BY create_date DESC` |

### 1.4 模糊搜索

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 16 | 客户名称里包含"科技"的公司 | `WHERE customer_name LIKE '%科技%'` |
| 17 | 商机名称里有"教育"的项目 | `WHERE opp_name LIKE '%教育%'`，"项目"→商机 |
| 18 | 查一下名字带"锐捷"的客户 | `WHERE customer_name LIKE '%锐捷%'` |
| 19 | 联系人姓名包含"王"的 | `WHERE contact_name LIKE '%王%'` |
| 20 | 部门是"信息化"开头的联系人 | `WHERE department LIKE '信息化%'` |

---

## 二、多条件组合查询（10题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 21 | 意向等级为高的华东区域客户 | 条件 AND：intent_level='高' AND region='华东' |
| 22 | 既是黑马客户又近30天没有互动的客户 | attribute='H' AND interaction_count_30d=0 |
| 23 | 商机金额超过100万且预计30天内开标的项目 | amount_10k>=100 AND expect_bid_date BETWEEN |
| 24 | 华东或华南区域的高意向客户 | region IN ('华东','华南') AND intent_level='高' |
| 25 | 在途商机金额大于0但联系人数量为0的客户 | active_opp_amount>0 AND contact_count=0 |
| 26 | 近30天互动超过5次且意向等级不低的客户 | interaction_count_30d>5 AND intent_level!='低' |
| 27 | 不是老客户但近30天有互动的 | is_existing_customer=0 AND interaction_count_30d>0 |
| 28 | 处于采购阶段4且在途商机金额大于50万的客户 | purchase_stage='阶段4…' AND active_opp_amount>50 |
| 29 | 金融或政府行业，且已进入漏斗的商机 | industry IN ('金融','政府') AND is_funnel='是' |
| 30 | 近30天互动次数在5到20之间的客户 | interaction_count_30d BETWEEN 5 AND 20 |

---

## 三、聚合统计查询（10题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 31 | 每个行业有多少个客户 | GROUP BY industry, COUNT(*)，"行业"→industry |
| 32 | 各区域在意向等级为高的客户数是多少 | GROUP BY region, COUNT(CASE WHEN intent_level='高'...) |
| 33 | 每个负责人手里客户的平均意向分数 | GROUP BY owner_name, AVG(intent_score) |
| 34 | 按采购阶段统计在途商机总金额 | GROUP BY purchase_stage, SUM(active_opp_amount) |
| 35 | 哪个渠道的互动量最高，占比是多少 | GROUP BY channel, COUNT(*), 百分比子查询 |
| 36 | 各产品类别商机数量和总金额 | GROUP BY product_category, COUNT(*), SUM(amount_10k) |
| 37 | 按负责人统计高意向客户占比 | GROUP BY owner_name, COUNT CASE / COUNT * 100 |
| 38 | 每个客户的联系人数和总互动次数 | 从 dws_customer_360 取 contact_count, interaction_count_total |
| 39 | 各月创建了多少商机，总金额多少 | GROUP BY DATE_FORMAT(create_date, '%Y-%m') |
| 40 | 统计DWS层各表有多少条数据 | UNION ALL 跨表 COUNT(*) |

---

## 四、JOIN 多表关联查询（10题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 41 | 查询所有决策者联系人及其所属客户名称和行业 | JOIN dws_contact_360 WITH dws_customer_360 ON customer_id，role_category='决策者' |
| 42 | 哪些客户有技术评估者角色但还没有商机 | JOIN + active_opp_count=0，识别"技术评估者" |
| 43 | 查询某个客户的商机，同时展示其负责人信息 | JOIN ods_crm_opportunity_day WITH dws_customer_360 |
| 44 | 列出活跃度为高的联系人，同时显示其客户的采购阶段 | JOIN dws_contact_360.activity_level='高' WITH dws_customer_360.purchase_stage |
| 45 | 通过手机号关联，查询致趣联系人在CRM中的对应记录 | JOIN ods_zhique_contact_day with ods_crm_contact_day ON mobile |
| 46 | 哪些客户有高价值互动行为但没有进入漏斗的商机 | JOIN dws_interaction_detail.is_high_value=1 WITH dws_customer_360.funnel_opp_count=0 |
| 47 | 查询有互动但没有商机的客户，按互动次数排序 | LEFT JOIN dws_customer_360 WHERE active_opp_count=0，识别"没有商机" |
| 48 | 统计每个行业的技术评估者联系人数量 | JOIN + GROUP BY industry, role_category='技术评估者' |
| 49 | 查询决策者在近30天内有互动的客户 | 三层JOIN：dws_contact_360 → dws_customer_360 → interaction_count_30d>0 |
| 50 | 查询有商机但没有决策者联系人的客户，显示商机金额和赢率 | LEFT JOIN ods_crm_opportunity_day WITH dws_contact_360 ON customer_name，role_category IS NULL |

---

## 五、时间维度查询（8题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 51 | 今天有哪些客户产生了互动 | `WHERE DATE(event_time) = CURDATE()` |
| 52 | 最近30天创建的商机有哪些 | `WHERE create_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)` |
| 53 | 未来30天内预计开标的项目 | `WHERE expect_bid_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)` |
| 54 | 上月互动量最高的10个客户 | DATE_FORMAT 上个月 + GROUP BY customer_name |
| 55 | 查询最近60天产生的web行为有哪些，显示客户和联系人 | `WHERE channel = web`，"拜访"→not_visit_days |
| 56 | 统计最近7天、30天、90天的互动量趋势 | 多时段 CASE WHEN + COUNT |
| 57 | 按月统计今年商机创建趋势 | GROUP BY DATE_FORMAT(create_date, '%Y-%m')，年份过滤 |
| 58 | 最近一次互动在7天前的客户有哪些 | `last_interaction_time < DATE_SUB(NOW(), INTERVAL 7 DAY)` |

---

## 六、复合业务场景（7题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 59 | CDP核心KPI仪表盘：总客户数、总互动量、总商机数、转化率 | 多条子查询组合，KPI大盘 |
| 60 | 高意向但近30天无互动的客户，按意向分数排序 | intent_level='高' AND interaction_count_30d=0，"沉睡客户"需理解 |
| 61 | 每个行业的高/中/低意向客户数量分布（交叉透视） | GROUP BY industry, intent_level，交叉统计 |
| 62 | 找出"有互动但没有商机"的潜在机会客户 | interaction_count_30d>5 AND active_opp_count=0 |
| 63 | 查询每个负责人名下的客户数、总商机金额、高意向客户数和平均意向分 | GROUP BY owner_name，多聚合函数组合 |
| 64 | 哪些客户在近30天没有互动 | ICP客户 + interaction_count_30d=0 |
| 65 | 查询最近30天互动超过5次且有决策者联系人的客户 | JOIN + interaction_count_30d>5 + role_category='决策者' |

---

## 七、同义词语义理解测试（10题）

> 以下使用术语的**同义词/口语化表达**来提问，测试 AI 的术语映射能力。

| # | 测试问题 | 预期术语映射 |
|---|---------|-------------|
| 66 | 最近"触达"最多的前5个"单位"是哪个"赛道"的 | 触达→互动, 单位→客户, 赛道→行业(industry), 最近→近30天 |
| 67 | "大客户"里谁是"管事的"，怎么联系 | 大客户→黑马客户(attribute='H'), 管事的→决策者(role_category='决策者'), 怎么联系→mobile/email |
| 68 | 帮我看看"pipeline"里还有多少"机会" | pipeline→在途商机, 机会→商机 |
| 69 | 近一个月"触达"最多的前5个"单位" | 触达→互动, 单位→客户, 一个月→30天 |
| 70 | 哪些人"跟"的"项目"里没有丢单情况 | 跟→负责, 项目→商机, 丢单→is_cancel_lost='是' |
| 71 | 哪个"大区"的"商机金额"最高 | 大区→部门, 商机金额→active_opp_amount |
| 72 | "电邮"渠道的互动占比多少 | 电邮→email/channel='email' |
| 73 | 查一下"关键决策人"的联系"电话" | 关键决策人→决策者, 电话→手机号(mobile) |
| 74 | 哪些"KA客户"进入了"销售漏斗" | KA客户→黑马客户/大客户, 销售漏斗→漏斗内商机 |
| 75 | "邮件"渠道"触达"最多的"甲方"是谁 | 邮件→channel='email', 触达→互动(interaction), 甲方→客户(customer) |

---

## 八、边界与鲁棒性测试（10题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 76 | 查询所有客户（不限制数量） | 应主动加 LIMIT 或有提示，防止全表返回 |
| 77 | 查询互动明细中"下载资料"的行为 | 行为类型=下载资料，多词匹配 |
| 78 | 帮我查一下 | 默认查询客户信息 |
| 79 | 统计数量 | 过于模糊，默认统计客户数量 |
| 80 | 查看张三和李四共同负责的客户 | 多个owner_name OR 或 IN |
| 81 | 客户分级是H和M的有多少 | attribute IN ('H','M')，识别"客户分级"→attribute |
| 82 | 金额最大的那个商机是哪个客户的 | ORDER BY amount_10k DESC LIMIT 1，"金额"→商机金额 |
| 83 | 行业不是教育也不是政府的客户 | WHERE industry NOT IN ('教育','政府') |
| 84 | 采购阶段是空的客户有哪些 | WHERE purchase_stage IS NULL OR purchase_stage='' |
| 85 | 意向等级分别有哪几种 | SELECT DISTINCT intent_level |

---

## 九、数据质量与系统查询（5题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 86 | ETL同步状态怎么样 | `SELECT * FROM dws_sync_meta`，"ETL同步"→dws_sync_meta |
| 87 | 最近有同步失败的任务吗 | `WHERE status='failed' FROM dws_sync_log` |
| 88 | 需人工审核的合并队列还有多少条 | `WHERE status='pending' FROM dws_review_queue` |
| 89 | 看一下上次数据同步跑了多长时间 | dws_sync_log + TIMESTAMPDIFF |
| 90 | 客户360表里有多少条重复的客户名称 | GROUP BY customer_name HAVING COUNT(*)>1 |

---

## 十、致趣与营销数据查询（6题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 91 | 系统里有哪些联系人是新客户 | ods_zhique_contact_day, is_new_customer=1 |
| 92 | 行为类型统计每种行为的事件数 | GROUP BY behavior_type, ods_zhique_behavior_list_day |
| 93 | 查每个客户的事件记录 | ods_linkflow_events_day JOIN ods_linkflow_contacts_day |
| 94 | 邮件互动最多的客户 | ods_zhique_behavior_list_day，behavior_type 过滤 + GROUP BY customer_name |
| 95 | 最近180天有哪些"中低价值"行为，对应哪些客户 | ods_zhique_behavior_list_day，event_time近7天 + is_high_value=1 |
| 96 | 统计各渠道的"留资"转化率，按渠道排序 | ods_zhique_behavior_list_day，is_high_value=1 作为转化，按 channel 分组统计 |

---

## 十一、复杂分析场景（4题）

| # | 测试问题 | 预期要点 |
|---|---------|---------|
| 97 | 按行业统计：客户数、在途商机总额、成交总额、高意向占比、人均互动次数 | 多聚合函数 GROUP BY，人均=SUM/COUNT |
| 98 | 找出"商机赢率>50%且预计下月开标但还没有决策者联系人"的机会 | 多条件JOIN，赢率→win_rate，决策者→role_category，时间逻辑 |
| 99 | 按区域交叉统计：各采购阶段客户数和高意向客户占比 | GROUP BY region, purchase_stage，含占比子查询 |
| 100 | 对比新老客户的行为差异：分别统计近30天互动次数、在途商机数、平均意向分 | CASE WHEN is_existing_customer 分组统计 |

---

## 测试统计

| 类别 | 数量 |
|------|------|
| 基础查询 | 20 |
| 多条件组合查询 | 10 |
| 聚合统计查询 | 10 |
| JOIN 多表关联 | 10 |
| 时间维度查询 | 8 |
| 复合业务场景 | 7 |
| 同义词语义理解 | 10 |
| 边界与鲁棒性 | 10 |
| 数据质量与系统 | 5 |
| 致趣与营销数据 | 6 |
| 复杂分析场景 | 4 |
| **合计** | **100** |
