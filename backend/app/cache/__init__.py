"""应用缓存包的公共入口。

业务代码优先从 ``app.cache`` 导入公共对象，不需要了解它们分别位于哪个实现文件。
这样既保持调用端简洁，也由 ``__all__`` 明确约束本包对外承诺的 API。
"""

# Redis 客户端生命周期与健康状态。
from app.cache.client import close_cache_client, get_cache_status

# 面向大规模客户名称集合的 Sorted Set 分页缓存。
from app.cache.customer_name_catalog import CustomerNameCatalog, customer_name_catalog

# 面向普通接口 JSON 响应的通用 Cache-Aside 服务。
from app.cache.service import CacheResult, CacheService, cache_service

# ``from app.cache import *`` 时只导出这些名称；它也可作为公共 API 清单阅读。
__all__ = [
    "CacheResult",
    "CacheService",
    "CustomerNameCatalog",
    "cache_service",
    "customer_name_catalog",
    "close_cache_client",
    "get_cache_status",
]
