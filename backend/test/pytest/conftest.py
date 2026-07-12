"""CDP 后端 pytest 共享基础设施。

设计目标
--------
- 默认 **mock 模式**：无需真实 MySQL / ES / LLM 即可运行全部接口测试。
- 通过 ``app.dependency_overrides`` 把 ``get_db`` 替换为 ``MockDBSession``，
  它会记录所有执行的 SQL，并支持按 SQL 子串返回预设结果。因此测试既能断言
  HTTP 响应结构，也能断言后端实际生成的 SQL（与既有 test_customer_filters.py 风格一致）。
- 对于不依赖 ``get_db`` 的路由（sync / es / ai / pool），在对应用例中用
  ``monkeypatch`` 替换底层服务函数或引擎/客户端，避免外部副作用。

目录结构
--------
    conftest.py            # 本文件：MockDBSession / 客户端 / mock_db fixture
    test_health.py         # 健康检查、未知路由
    test_customer_list.py  # 客户列表过滤 / 分页 / SQL 生成
    test_customer_detail.py# 客户 360 详情 / 联系人 / 互动 / 商机 / AI 洞察
    test_campaign.py       # 营销活动分析全部端点
    test_review.py         # 去重审核队列
    test_ai_chat.py        # AI 对话（mock LLM 服务）
    test_sync.py           # ETL 同步（mock 引擎）
    test_monitor.py        # 表数据量监控
    test_pool.py           # 连接池管理
    test_es.py             # ES CRUD / 同步（mock ES 服务）
    test_services_sql.py   # 服务层 SQL 生成逻辑
    test_etl_logic.py      # ETL 逻辑回归（tmp_icp_customers 修复）
    test_company_dedup.py  # 去重证据评分回归（IN 替代 LIKE 修复）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 将 backend/ 加入 sys.path，使 `from app...` 可被导入
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402


class Row:
    """轻量结果行，兼容 SQLAlchemy ``Row`` 的位置 / 键 / 属性访问与 ``dict()`` 转换。"""

    __slots__ = ("_data", "_keys", "_missing_none")

    def __init__(self, data: Dict[str, Any], missing_none: bool = False):
        self._data = data
        self._keys = list(data.keys())
        # 为 True 时，访问不存在的键 / 属性返回 None（用于聚合查询无数据的 one() 场景）
        self._missing_none = missing_none

    def __getitem__(self, key):
        if isinstance(key, int):
            if self._missing_none and key >= len(self._keys):
                return None
            return self._data[self._keys[key]]
        if self._missing_none and key not in self._data:
            return None
        return self._data[key]

    def __getattr__(self, name):
        # 仅在常规属性查找失败时触发，避免与 __slots__ 冲突
        if name in self._data:
            return self._data[name]
        if name != "_missing_none" and getattr(self, "_missing_none", False):
            return None
        raise AttributeError(name)

    def get(self, key, default=None):
        if isinstance(key, int):
            k = self._keys[key] if key < len(self._keys) else None
            return self._data.get(k, default) if k is not None else default
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __iter__(self):
        return iter(self._data)

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return f"Row({self._data!r})"


class MockResult:
    """兼容 SQLAlchemy ``Result`` 的常用方法。"""

    def __init__(
        self,
        rows: Optional[List[Dict[str, Any]]] = None,
        scalar: Any = None,
        rowcount: int = 0,
    ):
        self._rows = rows or []
        self._scalar = scalar
        self._rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return [Row(r) for r in self._rows]

    def fetchall(self):
        return [Row(r) for r in self._rows]

    def fetchone(self):
        return Row(self._rows[0]) if self._rows else None

    def first(self):
        return Row(self._rows[0]) if self._rows else None

    def one(self):
        # 兼容 SQLAlchemy Result.one()。聚合类查询即便无数据也返回一行（None 值），
        # 因此无数据时返回“缺失即 None”的空行，避免属性访问抛错。
        return Row(self._rows[0]) if self._rows else Row({}, missing_none=True)

    def scalar(self):
        return self._scalar

    @property
    def rowcount(self):
        return self._rowcount


class MockDBSession:
    """模拟 SQLAlchemy ``Session``：记录 SQL 并按子串匹配返回预设结果。"""

    def __init__(self):
        self.calls: List[tuple] = []
        self._matchers: List[tuple] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def add_result(
        self,
        match_substr: str,
        *,
        rows: Optional[List[Dict[str, Any]]] = None,
        scalar: Any = None,
        rowcount: int = 0,
    ) -> None:
        """注册一个响应：当执行的 SQL 包含 ``match_substr`` 时返回该结果。"""
        self._matchers.append((match_substr, MockResult(rows, scalar, rowcount)))

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, dict(params or {})))
        for substr, result in self._matchers:
            if substr in sql:
                return result
        # 默认返回：空结果集 + 计数为 0（贴近“无数据”但又不会因 None 引发 int(None)）
        return MockResult([], 0, 0)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def mock_db() -> MockDBSession:
    """返回一个干净的 MockDBSession，可在用例中通过 add_result 预设返回数据。"""
    return MockDBSession()


@pytest.fixture
def client(mock_db: MockDBSession) -> TestClient:
    """TestClient，并把 get_db 依赖替换为同一个 mock_db 实例。"""
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
