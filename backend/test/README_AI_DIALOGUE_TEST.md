# AI 对话功能测试数据集

## 测试覆盖场景

### 1. 客户360表查询（原有功能增强）

| 测试编号 | 用户查询 | 预期提取实体 | 预期目标表 |
|---------|---------|-------------|-----------|
| 1 | 查找广东地区医疗行业高意向的客户 | industry, region, intent_level | dws_customer_360 |
| 2 | 帮我找北京的企业客户，负责人是张三 | region, owner_name | dws_customer_360 |
| 3 | 哪些客户处于解决方案探索阶段？ | purchase_stage | dws_customer_360 |
| 4 | 查找有高价值商机的客户 | active_opp_count | dws_customer_360 |
| 5 | 哪些客户的决策人覆盖度是完整的？ | role_coverage | dws_customer_360 |
| 6 | 帮我找低意向的客户，近30天互动次数是0 | intent_level, interaction_count_30d | dws_customer_360 |
| 7 | 查找最近7天有互动的客户 | last_interaction_days | dws_customer_360 |
| 8 | 哪些客户的联系人总数超过10个？ | contact_count_min | dws_customer_360 |

### 2. 联系人表查询（新增功能）

| 测试编号 | 用户查询 | 预期提取实体 | 预期目标表 |
|---------|---------|-------------|-----------|
| 9 | 帮我看看这些客户的联系人都是谁 | query_type | dws_contact_360 |
| 10 | 查找联系人叫李四的客户 | contact_name | dws_contact_360 |
| 11 | 查找手机号是13800138000的联系人 | mobile | dws_contact_mapping |
| 12 | 哪些客户有决策者角色的联系人？ | role_category | dws_contact_360 |

### 3. 互动明细表查询（新增功能）

| 测试编号 | 用户查询 | 预期提取实体 | 预期目标表 |
|---------|---------|-------------|-----------|
| 13 | 查看最近客户访问官网的互动记录 | channel | dws_interaction_detail |
| 14 | 查找点击邮件链接的互动行为 | behavior_type | dws_interaction_detail |
| 15 | 查看最近30天的客户互动明细 | last_interaction_days | dws_interaction_detail |

### 4. 数据充足性判断（新增功能）

| 测试编号 | 用户查询 | 预期数据充足性提示 |
|---------|---------|-------------------|
| 16 | 这些客户的联系人是谁？ | 💡 提示：可以查询 dws_contact_360 获取联系人信息 |
| 17 | 查看客户的具体互动行为 | 💡 提示：可以查询 dws_interaction_detail 获取互动记录 |
| 18 | 查找客户在官网的访问记录 | ✅ 数据充足（查询 dws_interaction_detail） |

### 5. 简单问题和其他问题

| 测试编号 | 用户查询 | 预期意图 |
|---------|---------|---------|
| 19 | 你好 | simple_question |
| 20 | 今天天气怎么样？ | other |

---

## 运行测试

### 1. 运行单元测试

```bash
cd /home/liyanqi/workspace/ruijie/ruijie-cdp/backend
python -m pytest test/test_ai_dialogue.py -v
```

### 2. 运行集成测试（需要数据库连接）

```bash
cd /home/liyanqi/workspace/ruijie/ruijie-cdp/backend
python -m pytest test/test_ai_dialogue.py::TestProcessChat -v
```

### 3. 手动测试 API 端点

#### 测试意图识别

```bash
curl -X POST http://localhost:8000/api/ai/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "查找广东地区医疗行业高意向的客户"}'
```

#### 测试完整对话

```bash
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "查找广东地区医疗行业高意向的客户"}'
```

#### 测试联系人查询

```bash
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "查找联系人叫张三的客户"}'
```

#### 测试互动行为查询

```bash
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "查看客户访问官网的互动记录"}'
```

---

## 优化说明

### 1. 扩展实体提取能力

**原有功能**：只支持少量实体（industry, region, stage, intent_level, channel, keyword, interaction_min）

**优化后**：支持所有 `dws_customer_360` 字段：
- customer_name（客户公司名称）
- industry（所属行业）
- region（地域/区域）
- owner_name（公司拥有者名称/负责人）
- purchase_stage（发展阶段/采购阶段）
- role_coverage（人员覆盖度）
- intent_score（意向评分）
- intent_level（意向等级）
- interaction_count_30d（近30天互动次数）
- interaction_count_total（总互动次数）
- last_interaction_time（最近一次交互时间）
- last_interaction_channel（最近互动渠道）
- active_opp_count（活跃商机数量）
- active_opp_amount（活跃商机金额）
- contact_count（公司联系人总数）
- mobile_count（手机号数量）
- is_existing_customer（是否现有客户）

### 2. 支持多表查询

**原有功能**：只查询 `dws_customer_360` 表

**优化后**：支持查询以下4张表：
- `dws_customer_360`（客户360度视图）
- `dws_contact_360`（联系人360度视图）
- `dws_contact_mapping`（联系人跨系统映射表）
- `dws_interaction_detail`（互动明细表）

### 3. 智能判断数据充足性

**原有功能**：未明确告知用户数据充足性

**优化后**：
- 明确告知用户哪些数据查到了
- 明确告知用户哪些数据没查到，可能有风险
- 提供相关数据的查询建议
- 自动提示可以查询的其他表

### 4. 智能选择目标表

**新增功能**：根据用户查询内容，自动选择最合适的表进行查询

**判断逻辑**：
1. 如果查询条件中包含联系人相关字段，优先查询联系人表
2. 如果用户询问具体的互动行为、渠道、内容等，查询互动明细表
3. 如果用户明确询问联系人信息，查询联系人360表
4. 默认查询客户360表

---

## 文件修改清单

### 修改的文件

1. `backend/app/services/ai_service.py`
   - 新增：数据库表结构定义（`AVAILABLE_TABLES`）
   - 优化：`recognize_intent()` 函数（扩展实体提取）
   - 优化：`generate_sql()` 函数（支持多表）
   - 优化：`analyze_results()` 函数（增加数据充足性判断）
   - 新增：`_check_data_adequacy()` 函数（检查数据充足性）
   - 新增：`_select_target_table()` 函数（智能选择目标表）
   - 优化：`process_chat()` 函数（支持多表查询）
   - 优化：`export_query_results()` 函数（支持多表导出）

### 新增的文件

1. `backend/test/test_ai_dialogue.py`（测试脚本）

---

## 注意事项

1. **AI 模型依赖**：意图识别和结果分析依赖 DeepSeek 模型，需要确保 `LLM_API_KEY` 和 `LLM_BASE_URL` 配置正确

2. **数据库依赖**：SQL 生成和执行依赖数据库连接，需要确保数据库可访问

3. **字段匹配**：如果用户查询的字段在数据库中不存在，系统会给出提示和建议

4. **性能考虑**：
   - 意图识别需要调用 AI 模型（约 1-2 秒）
   - 结果分析需要调用 AI 模型（约 1-2 秒）
   - SQL 查询性能依赖数据库索引

5. **降级处理**：如果 AI 模型调用失败，系统会降级为通用回答

---

## 后续优化建议

1. **缓存意图识别结果**：对于相同的查询，可以缓存识别结果，减少模型调用

2. **支持更多表**：如果需要查询其他表，可以在 `AVAILABLE_TABLES` 中添加

3. **优化提示词**：根据实际使用效果，持续优化意图识别的提示词

4. **增加日志**：记录用户查询和识别结果，用于后续分析和优化

5. **支持多轮对话**：当前版本对多轮对话的支持有限，可以后续优化
