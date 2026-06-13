# 公司名去重功能对照与待补全清单

## 已实现 vs 文档要求

| 文档章节 | 需求 | 实现 | 状态 |
|---|---|---|---|
| 10.2 Step 1 | NER提取、清理括号后缀 | `normalize_company_name()` | ✅ |
| 10.2 Step 2 | 编辑距离、包含、后缀 | `calculate_rule_score()` | ✅ |
| 10.2 Step 3 | 共享手机号/邮箱证据 | `calculate_evidence_score()` | ✅ |
| 10.2 Step 4 | **大模型校验** | ❌ 缺失 | 🔴 待实现 |
| 10.2 Step 5 | rule+evidence+llm 加权 | embedding代替llm | ⚠️ 部分 |
| 10.2 Step 5 | 阈值>0.85/0.6/0.6 | 代码90/75 | ⚠️ 不同 |
| 10.2 Step 6 | **最新数据优先级CRM>线索>...** | ❌ 缺失 | 🔴 待实现 |

## 待补全功能

### 1. LLM 校验（高优先级）

```python
def llm_judge(company_a: str, company_b: str, evidence: dict) -> tuple[float, str]:
    """调用LLM判断两个公司名是否同一主体。
    
    输入：公司A、公司B、共享证据（手机号、邮箱、行业、省份）
    输出：(置信分0-100, 解释文本)
    
    判断规则：
    - 简称与全称（"阿里" vs "阿里巴巴"）→ 高分
    - 不同法人实体但业务相关 → 中等分
    - 完全不同的公司 → 低分
    """
```

### 2. 统一阈值调整

当前：≥90自动合并，≥75人工审核
文档：>85自动合并，>60人工审核，≤60不聚合

### 3. 最新数据优先级逻辑

```python
# 数据源优先级排序（高→低）
SOURCE_PRIORITY = {
    'crm': 6,
    'lead': 5,
    'tianrun_session': 4,
    'zhique_behavior': 3,
    'linkflow': 2,
    'email_click': 1,
}

def pick_latest_data(candidates):
    """选择最新一条公司数据。
    优先级：1.最近业务时间最大  2.同日按SOURCE_PRIORITY排序
    """
```

### 4. 公司名合并落库

```sql
-- 合并后保留 aliases 和 source_lineage
UPDATE dws_customer_360 
SET aliases = JSON_ARRAY_APPEND(aliases, '$', :merged_name),
    source_lineage = JSON_MERGE(source_lineage, :new_source_lineage)
WHERE customer_name = :primary_name
```