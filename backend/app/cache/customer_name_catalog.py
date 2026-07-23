"""基于 Redis Sorted Set 的客户名称目录缓存。

通用 JSON 缓存会拒绝超过 1 MiB 的单个值，而客户名称下拉框需要保存完整名称目录，
又不能一次把全部名称返回浏览器。本模块因此采用不同的数据结构：

* 一个“专项范围”对应一个 Sorted Set；
* 每个客户名称作为独立 member 存储，所有 score 都设为 0；
* 利用 member 的字典序进行前缀检索，并只读取指定 offset/limit 的一页；
* 首次构建使用临时 key，完成后原子 rename，避免读到半成品；
* Redis 不可用时仍然通过 MySQL 的分页 loader 返回结果。
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any, Optional

from app.cache.client import get_cache_client
from app.cache.service import CacheResult, CacheService, cache_service, canonical_params_hash
from app.config import settings

logger = logging.getLogger(__name__)

# 与通用缓存相同的安全解锁脚本：只有 token 与当前锁值一致时才删除锁。
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

# 目录 key 的业务命名空间；最终仍由 CacheService 加上环境、版本和参数指纹。
_CATALOG_NAMESPACE = "customer:name-catalog"

# Sorted Set member 编码为：casefold 后的名称 + NUL 分隔符 + 原始名称。
# NUL 不会出现在正常客户名称中，便于无损取回原始大小写文本。
_MEMBER_SEPARATOR = b"\x00"

# 单次 ZADD 最多包含 1000 个名称；一个 pipeline 最多容纳 10 个这样的命令。
# 分批可限制客户端内存、命令体大小和 Redis 单次处理时长。
_ZADD_CHUNK_SIZE = 1000
_PIPELINE_CHUNKS = 10


def _member_for_name(name: str) -> bytes:
    """生成支持忽略大小写前缀检索、同时保留原始名称的 member。"""
    encoded_name = name.encode("utf-8")
    # casefold 比 lower 更适合 Unicode 大小写归一化；原始文本放在分隔符后用于展示。
    return name.casefold().encode("utf-8") + _MEMBER_SEPARATOR + encoded_name


def _name_from_member(member: Any) -> str:
    """从 Redis member 中解析出用于页面展示的原始客户名称。"""
    if isinstance(member, str):
        member = member.encode("utf-8")
    _, separator, encoded_name = bytes(member).partition(_MEMBER_SEPARATOR)
    # 兼容可能存在的旧格式：没有分隔符时，整个 member 就是名称。
    payload = encoded_name if separator else bytes(member)
    return payload.decode("utf-8")


class CustomerNameCatalog:
    """按专项范围构建完整名称目录，并从 Redis 中分页读取。"""

    def __init__(
        self,
        client_provider: Callable[[], Any] = get_cache_client,
        shared_cache: CacheService = cache_service,
    ) -> None:
        # provider 延迟获取共享 Redis；shared_cache 复用统一的 key 规范与 TTL 抖动。
        # 两个依赖都可注入，因此单元测试无需连接真实 Redis。
        self._client_provider = client_provider
        self._shared_cache = shared_cache

    def build_key(self, special_project: Sequence[str]) -> tuple[str, str]:
        """根据专项列表生成目录 key，并返回对应范围指纹。"""
        return self._shared_cache.build_key(
            _CATALOG_NAMESPACE,
            {"special_project": list(special_project)},
        )

    @staticmethod
    def _read_page(
        client: Any,
        key: str,
        *,
        query: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        """读取一页目录；有查询词时按 member 字典序做前缀匹配。"""
        # 多取一个元素用于判断 has_more，不需要额外执行 COUNT。
        stop = offset + limit
        if query:
            prefix = query.casefold().encode("utf-8")
            # 所有 member 的 score 都是 0，因此 ZRANGEBYLEX 可以按 member 排序。
            # [prefix 表示包含前缀下界；(prefix+0xff 形成不包含的近似上界。
            members = client.zrangebylex(
                key,
                b"[" + prefix,
                b"(" + prefix + b"\xff",
                start=offset,
                num=limit + 1,
            )
        else:
            # zrange 的 stop 是闭区间，offset + limit 正好能够多取一个元素。
            members = client.zrange(key, offset, stop)
        names = [_name_from_member(member) for member in members]
        return {
            "items": names[:limit],
            "has_more": len(names) > limit,
        }

    @staticmethod
    def _write_catalog(
        client: Any,
        key: str,
        ready_key: str,
        names: Sequence[str],
        ttl_seconds: int,
        token: str,
    ) -> tuple[int, int]:
        """分批构建临时 Sorted Set，完成后原子替换正式目录。"""
        # 每个构建请求使用独立临时 key，即使上一次构建中断也不会污染正式目录。
        temp_key = f"{key}:building:{token}"
        # 清理空值、前后空格和重复名称；排序让构建输入保持确定性。
        normalized_names = sorted({name.strip() for name in names if name and name.strip()})
        ttl = CacheService._jittered_ttl(ttl_seconds)
        # 记录原始名称字节数仅用于日志观测，不代表 Redis 的完整内存占用。
        raw_name_bytes = sum(len(name.encode("utf-8")) for name in normalized_names)
        # 理论上 token 唯一；仍先删除同名临时 key，使重试具有幂等性。
        client.delete(temp_key)

        try:
            pipeline_width = _ZADD_CHUNK_SIZE * _PIPELINE_CHUNKS
            for batch_start in range(0, len(normalized_names), pipeline_width):
                # 非事务 pipeline 只减少网络往返，不要求每批命令原子执行。
                pipeline = client.pipeline(transaction=False)
                batch = normalized_names[batch_start:batch_start + pipeline_width]
                for chunk_start in range(0, len(batch), _ZADD_CHUNK_SIZE):
                    chunk = batch[chunk_start:chunk_start + _ZADD_CHUNK_SIZE]
                    pipeline.zadd(
                        temp_key,
                        # score 统一为 0，实际顺序完全由 member 的字典序决定。
                        {_member_for_name(name): 0 for name in chunk},
                    )
                # 构建期间也设置过期时间，防止进程中断后遗留永久临时 key。
                pipeline.expire(temp_key, max(ttl, 60))
                pipeline.execute()

            # 最终发布需要事务：目录替换、TTL 和 ready 标记必须一起生效。
            finalizer = client.pipeline(transaction=True)
            if normalized_names:
                # RENAME 是原子操作，读请求只会看到旧目录或完整的新目录。
                finalizer.rename(temp_key, key)
                finalizer.expire(key, ttl)
            else:
                # 空目录不创建 Sorted Set，ready_key 用于区分“构建完成但为空”和“未构建”。
                finalizer.delete(key)
            finalizer.set(ready_key, b"1", ex=ttl)
            finalizer.execute()
        except Exception:
            # 构建失败时尽力回收临时 key；原正式目录不受影响。
            try:
                client.delete(temp_key)
            except Exception:
                pass
            raise

        # 返回构建规模，供调用方输出结构化日志。
        return len(normalized_names), raw_name_bytes

    def get_page(
        self,
        *,
        special_project: Sequence[str],
        query: str,
        offset: int,
        limit: int,
        ttl_seconds: int,
        catalog_loader: Callable[[], Sequence[str]],
        page_loader: Callable[[], dict[str, Any]],
        defer_build: Optional[Callable[[], None]] = None,
        cacheable: bool = True,
        endpoint: str = "/api/customers/name-options",
    ) -> CacheResult:
        """返回一页客户名称；目录尚未就绪时负责构建，并在故障时降级。

        ``catalog_loader`` 一次从数据库读取完整名称目录，仅在首次构建/过期重建时
        使用；``page_loader`` 只查询当前页，供缓存关闭、异步构建中或 Redis 异常时
        快速兜底。若传入 ``defer_build``，当前请求触发后台构建后立即走分页兜底，
        不在请求线程内等待完整目录生成。
        """
        # key/scope_hash 只与专项范围相关：同一范围下的所有搜索词和页共享一个目录。
        key, scope_hash = self.build_key(special_project)

        # Sorted Set 为空时 Redis 不保留 key，所以另设 ready 标记来表达“空目录已构建”。
        ready_key = f"{key}:ready"

        # request_hash 包含具体搜索词和分页参数，只用于单次请求日志关联。
        request_hash = canonical_params_hash({
            "special_project": list(special_project),
            "q": query.casefold(),
            "offset": offset,
            "limit": limit,
        })
        started_at = time.perf_counter()

        def fallback(status: str) -> CacheResult:
            """绕过目录缓存，直接从 MySQL 读取当前页并记录降级耗时。"""
            db_started = time.perf_counter()
            value = page_loader()
            logger.info(
                "cache_request endpoint=%s namespace=%s status=%s cache_ms=%.2f "
                "db_ms=%.2f params_hash=%s scope_hash=%s",
                endpoint,
                _CATALOG_NAMESPACE,
                status,
                (db_started - started_at) * 1000,
                (time.perf_counter() - db_started) * 1000,
                request_hash,
                scope_hash,
            )
            return CacheResult(value, status, params_hash=request_hash)

        # 业务范围不允许缓存，或全局缓存关闭时，不获取 Redis 客户端。
        if not cacheable or not settings.CACHE_ENABLED:
            return fallback("BYPASS")

        try:
            client = self._client_provider()
            if client is None:
                return fallback("BYPASS")

            # ready 已存在意味着完整目录可读，默认状态为 HIT。
            status = "HIT"
            if not client.get(ready_key):
                if defer_build is not None:
                    # 将全量构建交给 FastAPI 后台任务；本次请求使用数据库分页结果。
                    defer_build()
                    return fallback("MISS")

                # 没有后台构建器时，在当前请求内争抢构建锁。锁按目录 key 生成，同一
                # 专项范围同一时刻只允许一个请求全量扫描数据库。
                token = uuid.uuid4().hex
                lock_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
                lock_key = f"{self._shared_cache._key_prefix()}:lock:{lock_hash}"
                acquired = bool(client.set(
                    lock_key,
                    token.encode("ascii"),
                    # NX 提供互斥；PX 让持锁进程崩溃后锁也会自动释放。
                    nx=True,
                    px=settings.CACHE_LOCK_TTL_MS,
                ))
                if acquired:
                    try:
                        # 当前请求成为构建者：读取全量名称，再分批写入临时 Sorted Set。
                        build_started = time.perf_counter()
                        names = catalog_loader()
                        name_count, raw_name_bytes = self._write_catalog(
                            client,
                            key,
                            ready_key,
                            names,
                            ttl_seconds,
                            token,
                        )
                        logger.info(
                            "customer_name_catalog_built count=%d raw_name_bytes=%d "
                            "build_ms=%.2f scope_hash=%s",
                            name_count,
                            raw_name_bytes,
                            (time.perf_counter() - build_started) * 1000,
                            scope_hash,
                        )
                        # MISS 表示本次请求完成了目录构建，随后仍会从 Redis 读取当前页。
                        status = "MISS"
                    finally:
                        # Lua 脚本只释放 token 仍属于自己的锁，避免删除后来者的锁。
                        try:
                            client.eval(
                                _RELEASE_LOCK_SCRIPT,
                                1,
                                lock_key,
                                token.encode("ascii"),
                            )
                        except Exception as exc:
                            logger.warning("Failed to release customer-name catalog lock: %s", exc)
                else:
                    # 其他请求正在构建，最多等待约 500ms 检查 ready 标记。
                    for _ in range(5):
                        time.sleep(0.1)
                        if client.get(ready_key):
                            break
                    if not client.get(ready_key):
                        # 不继续阻塞 HTTP 请求；直接查数据库当前页，且不干扰构建者。
                        return fallback("MISS")

            # 此时 ready 已就绪，从 Redis 有界读取当前页，不把完整目录传给浏览器。
            value = self._read_page(
                client,
                key,
                query=query,
                offset=offset,
                limit=limit,
            )
            # ready_key 与目录使用相同 TTL；读取它即可报告整个目录的剩余寿命。
            ttl = max(0, int(client.ttl(ready_key) or 0))
            logger.info(
                "cache_request endpoint=%s namespace=%s status=%s cache_ms=%.2f "
                "db_ms=0.00 items=%d params_hash=%s scope_hash=%s",
                endpoint,
                _CATALOG_NAMESPACE,
                status,
                (time.perf_counter() - started_at) * 1000,
                len(value["items"]),
                request_hash,
                scope_hash,
            )
            return CacheResult(value, status, ttl, request_hash)
        except Exception as exc:
            # 任意 Redis/序列化/构建异常都 fail-open，改由分页 loader 查询 MySQL。
            logger.warning(
                "Customer-name catalog unavailable; falling back to MySQL: %s",
                exc,
            )
            return fallback("ERROR")


# 默认共享目录服务，路由层通常直接导入该实例。
customer_name_catalog = CustomerNameCatalog()
