# CDP ABM 360 — 前后端联调修复方案

> **For agentic workers:** 按 Task 顺序执行，每个 Task 完成后验证再下一个。

**Goal:** 修复客户详情页业务标签、互动时间线、后端500问题，完成前后端字段全面对齐

**Architecture:** 三层修复：后端连接 → 前端数据流 → 字段映射表

**Tech Stack:** FastAPI + Vue3 + MySQL

---

## 任务分解

### Task 1: 重启后端服务

**Files:**
- 无代码修改，仅操作

- [ ] **Step 1: 杀掉旧后端进程**

```bash
# 找到占端口的进程
netstat -ano | findstr ":8000"
# 得到 PID (如 81244)
taskkill /F /PID 81244
```

- [ ] **Step 2: 重新启动后端**

```bash
cd D:/日志/06/cdp/backend && env/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 3: 验证**

```bash
curl http://127.0.0.1:8000/api/health
# 应返回 {"status":"ok","service":"CDP ABM 360"}
curl "http://127.0.0.1:8000/api/customers?page=1&size=2"
# 应返回客户数据，而不是 Internal Server Error
```

---

### Task 2: 修复互动时间线（CustomerDetail 数据解包）

**Files:**
- Modify: `frontend/src/views/CustomerDetail.vue:33-35`

**问题**：后端返回 `{customer_id, customer_name, interactions: [...]}`，但前端直接存了整个对象，传给 BehaviorTimeline 的不是数组。

- [ ] **Step 1: 修改数据解包**

```javascript
// CustomerDetail.vue — fetchAllData 中的赋值
// 改前:
interactions.value = interactionsRes

// 改后:
customer.value = detailRes
contacts.value = Array.isArray(contactsRes) ? contactsRes : (contactsRes.contacts || [])
interactions.value = Array.isArray(interactionsRes) ? interactionsRes : (interactionsRes.interactions || [])
opportunities.value = Array.isArray(oppsRes) ? oppsRes : (oppsRes.opportunities || [])
aiInsight.value = aiRes
```

- [ ] **Step 2: 验证前端 build**

```bash
cd D:/日志/06/cdp/frontend && npm run build
```

---

### Task 3: 修复业务标签组件字段映射

**Files:**
- Modify: `frontend/src/components/detail/OverviewTab.vue:18-70`
- Modify: `frontend/src/components/detail/BusinessTags.vue`
- Modify: `frontend/src/components/detail/FollowupStatus.vue`
- Modify: `frontend/src/components/detail/OpportunityBudget.vue`

**核心问题**：OverviewTab.vue 给子组件传的 prop 与 dws_customer_360 实际列名不完全匹配。需要建立正确的列名映射表。

- [ ] **Step 1: 建立字段映射表**

| 组件 Prop | 当前传的值 | 应传的值 | 说明 |
|---|---|---|---|
| KpiCards:intent | customer.intent | `customer.intent_level` | 正确 ✅ |
| KpiCards:interactionCount | customer.interactionCount | `customer.interaction_count_30d` | 改列名 |
| KpiCards:stage | customer.stage | `customer.purchase_stage` | 正确 ✅ |
| KpiCards:keyRoles | customer.keyRoles | `customer.role_coverage` | 正确 ✅ |
| CustomerProfile:owner | customer.owner | `customer.owner_name` | 正确 ✅ |
| CustomerProfile:telecomAddress | customer.telecomAddress | `customer.region` | 暂用区域代替 |
| CustomerProfile:isExistingCustomer | customer.isExistingCustomer | `customer.is_existing_customer` | 正确 ✅ |
| **BusinessTags:demandTypes** | `customer.product_categories` | **暂显示"暂无数据"** | dws 表无此字段 |
| **BusinessTags:businessScenarios** | `customer.source_tables` | `customer.industry` | 行业作为场景占位 |
| **BusinessTags:painPoints** | `customer.data_coverage` | **暂显示"暂无数据"** | dws 表无此字段 |
| FollowupStatus:lastInteraction | customer.lastInteraction | `customer.last_interaction_time` | 正确 ✅ |
| FollowupStatus:preferredChannels | customer.preferredChannels | `customer.top_channels` | 需格式化为可读文本 |
| OpportunityBudget:recentDeals | customer.recentDeals | `customer.won_amount` | 需格式化为"X万元" |

- [ ] **Step 2: 修改 OverviewTab.vue — 修正所有 prop 映射**

```diff
- intent="customer.intent"
+ intent="customer.intent_level"

- interactionCount="customer.interactionCount || 0"
+ interactionCount="customer.interaction_count_30d || 0"

- stage="customer.stage"
+ stage="customer.purchase_stage"

- keyRoles="customer.keyRoles"
+ keyRoles="customer.role_coverage"

- owner="customer.owner"
+ owner="customer.owner_name"

- telecomAddress="customer.telecomAddress"
+ telecomAddress="customer.region"

- isExistingCustomer="customer.isExistingCustomer"
+ isExistingCustomer="customer.is_existing_customer"

- demandTypes="customer.demandTypes"
+ demandTypes="customer.product_categories"

- businessScenarios="customer.businessScenarios"
+ businessScenarios="customer.industry"

- painPoints="customer.painPoints"
- painPoints 无数据 -> 传空数组 []

- productCategories="customer.productCategories"
+ productCategories="customer.product_categories"

- lastInteraction="customer.lastInteraction"
+ lastInteraction="customer.last_interaction_time"

- preferredChannels="customer.preferredChannels"
+ preferredChannels="customer.top_channels"

- funnelCount="opportunities?.length || 0"
+ funnelCount="customer.funnel_opp_count || 0"

- highestStage="opportunities?.[0]?.stage || '-'"
+ highestStage="customer.forecast_type || '-'"

- recentDeals="customer.recentDeals"
+ recentDeals="customer.won_amount"
```

- [ ] **Step 3: 修改 BusinessTags.vue — 处理空数据**

```javascript
// 当前组件可能直接遍历 props.demandTypes，但现在是 null/undefined，
// 需要加空值保护

// 在模板中:
v-if="demandTypes && demandTypes.length > 0" // 显示标签
v-else // 显示"暂无需求类型数据"
```

- [ ] **Step 4: 修改 FollowupStatus.vue — 格式化 channels**

```javascript
// top_channels 是 JSON 数组 ["email","web"]，需要转为中文
// 可用 computed:
const channelLabels = {
  email: '邮件', web: '官网', event: '直播/活动', wechat: '微信'
}

// 或简单字符串替换显示
```

- [ ] **Step 5: 修改 OpportunityBudget.vue — 格式化金额**

```javascript
// won_amount 是数字 (万元)，显示为 "X万元"
// funnel_opp_count 如果大于0，显示漏斗详情
```

- [ ] **Step 6: 验证前端 build**

```bash
cd D:/日志/06/cdp/frontend && npm run build
```

---

### Task 4: API 端到端验证

**Files:**
- 无代码修改

- [ ] **Step 1: 验证健康检查**

```bash
curl http://127.0.0.1:8000/api/health
# → {"status":"ok"}
```

- [ ] **Step 2: 验证客户列表**

```bash
curl "http://127.0.0.1:8000/api/customers?page=1&size=2"
# → {"total": 1012, "items": [...]}
```

- [ ] **Step 3: 验证客户详情**

```bash
curl http://127.0.0.1:8000/api/customers/1
# → 包含 customer_name, industry, owner_name, intent_level 等字段
```

- [ ] **Step 4: 验证互动时间线**

```bash
curl http://127.0.0.1:8000/api/customers/1/interactions?limit=3
# → {"customer_id": "1", "interactions": [...]}
#    interactions 是数组
```

- [ ] **Step 5: 验证联系人**

```bash
curl http://127.0.0.1:8000/api/customers/1/contacts
# → 联系人列表或空数组
```

- [ ] **Step 6: 提交 Git**

```bash
cd D:/日志/06/cdp && git add . && git commit -m "fix: align frontend-detail fields with backend schema, fix pagination and interaction timeline data flow"
```

---

## 验证清单

```markdown
### 列表页
- [ ] 显示 1012 个 ICP 客户
- [ ] 分页：1 2 3 ... 51 上一页/下一页/输入跳转
- [ ] 筛选：按行业、负责人、互动次数、渠道
- [ ] 导出按钮

### 详情页-概览
- [ ] KPI 卡片：意向、互动、阶段、角色覆盖、在途商机
- [ ] 客户档案：行业、区域、负责人、通讯地址、老客户标识
- [ ] 业务标签：需求类型、业务场景、历史产品
- [ ] 跟进状态：最近互动、偏好渠道
- [ ] 商机预算：漏斗商机、最阶段、成交金额
- [ ] 互动时间线：来源、渠道、互动人、内容
- [ ] AI 洞察：业务结论、联系人 Top3、证据链

### 详情页-联系人
- [ ] AI 优先推进对象
- [ ] 联系人卡片列表
- [ ] 按角色筛选