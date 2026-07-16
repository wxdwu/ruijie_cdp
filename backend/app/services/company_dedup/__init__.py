"""公司去重与审核队列服务子包。

聚合去重流水线核心逻辑（company_dedup），供审核队列 router 及测试复用。
"""

from . import company_dedup

__all__ = ["company_dedup"]
