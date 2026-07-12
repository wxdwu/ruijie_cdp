# CDP 后端接口自动化测试

本目录是基于 `pytest` + `FastAPI TestClient` 的后端接口测试套件，工程化、可重复、无需真实数据库即可运行。

## 设计原则

1. **默认 mock 模式**：通过 `app.dependency_overrides` 把 `get_db` 替换为内存版 `MockDBSession`
   （见 `conftest.py`）。它记录所有执行的 SQL，并支持按 SQL 子串返回预设结果，因此测试既能断言 HTTP
   响应结构，也能断言后端实际生成的 SQL。
2. **零外部依赖**：不依赖真实 MySQL / Elasticsearch / DeepSeek。对于不经由 `get_db` 的路由
   （`sync` / `es` / `ai` / `pool`），在用例内用 `monkeypatch` 替换底层服务函数、引擎或客户端。
3. **可读可维护**：每个路由一个 `test_*.py`，命名清晰；服务层 SQL 生成逻辑单独测试。

## 目录结构

```
conftest.py            # MockDBSession / Row / MockResult / client / mock_db fixture
test_health.py         # 健康检查、未知路由 404
test_customer_list.py  # 客户列表：过滤 SQL 生成、分页信封
test_customer_detail.py# 客户 360 详情/联系人/互动/商机/AI 洞察
test_campaign.py       # 营销活动分析全部端点
test_review.py         # 去重审核队列（列表/统计/通过/拒绝/批量）
test_ai_chat.py        # AI 对话（mock LLM 服务）
test_sync.py           # ETL 同步（mock 引擎/服务）
test_monitor.py        # 表数据量监控
test_pool.py           # 连接池管理
test_es.py             # ES CRUD / 同步（mock ES 服务）
test_services_sql.py   # 服务层 SQL 生成逻辑（opportunity / interaction）
test_etl_logic.py      # ETL 逻辑回归（tmp_icp_customers 修复）
test_company_dedup.py  # 去重证据评分回归（IN 替代 LIKE 修复）
pytest.ini             # pytest 配置
requirements-test.txt  # 测试依赖
```

## 运行方式

在 `backend/` 目录下执行（确保已安装后端运行依赖，再装测试依赖）：

```bash
# 1. 安装测试依赖
pip install -r test/pytest/requirements-test.txt

# 2. 运行全部测试
python -m pytest test/pytest -q

# 3. 运行指定文件 / 用例
python -m pytest test/pytest/test_customer_detail.py -v
python -m pytest test/pytest/test_etl_logic.py -v

# 4. 显示打印与最慢用例
python -m pytest test/pytest -v -s --durations=10
```

> 提示：测试默认使用 mock，不会连接 `backend/.env` 中的数据库。若环境缺少 `pymysql` /
> `fastapi` 等依赖，请先 `pip install -r test/pytest/requirements-test.txt`（以及后端运行依赖）。

## 回归守护

- `test_etl_logic.py`：确保 `dws_contact_mapping` 载入查询引用 `tmp_icp_customers` 而非已废弃的
  `tmp_icp_companies`。
- `test_company_dedup.py`：确保 `batch_calculate_evidence_scores` 使用精确 `IN (...)` 匹配，
  而非上千条 `LIKE` 链式条件。
