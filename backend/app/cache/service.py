"""通用的 Redis JSON 旁路缓存（Cache-Aside）服务。

业务路由只需提供缓存命名空间、查询参数、TTL 和数据库 loader。本模块负责：

* 将等价的查询参数规范化并生成稳定缓存键；
* 在 Redis 命中时直接返回 JSON，在未命中时调用 loader 并回填缓存；
* 通过 TTL 抖动和短时分布式锁缓解缓存雪崩、缓存击穿；
* 在 Redis 故障时 fail-open，仍然返回数据库结果；
* 记录 HIT、MISS、BYPASS、ERROR 以及耗时、大小等观测信息。

该实现用于同步 FastAPI 路由，因此 Redis 和 loader 调用也都是同步的。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from fastapi.encoders import jsonable_encoder

from app.cache.client import get_cache_client
from app.config import settings

logger = logging.getLogger(__name__)

# 用专用哨兵区分“loader 尚未执行”和“loader 合法返回 None”。
_MISSING = object()

# 释放锁不能直接 DEL：锁过期后可能已被其他请求重新获得。Lua 脚本先核对当前
# token，只允许锁的原持有者删除它；脚本在 Redis 中原子执行。
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class CacheResult:
    """一次缓存请求的结果与观测元数据。

    ``status`` 的含义：HIT=命中，MISS=本次从数据源加载，BYPASS=未使用缓存，
    ERROR=Redis 操作异常但已成功降级。``ttl_seconds`` 是 Redis 中实际剩余/写入
    的 TTL；``params_hash`` 可用于日志关联，但不会暴露完整查询参数。
    """

    value: Any
    status: str
    ttl_seconds: int = 0
    params_hash: str = ""


def _canonicalize(value: Any) -> Any:
    """把查询参数递归转换成稳定、可 JSON 序列化的形式。

    筛选项的顺序、重复值和空字符串不应制造不同缓存键。因此映射按 key 排序，
    集合型参数规范化后去重并排序，空字符串/空集合统一成 ``None``。这里把所有
    list/tuple/set 都视为无序筛选集合；若未来出现“顺序有业务含义”的参数，不应
    直接复用这一规则。
    """
    if isinstance(value, Mapping):
        # str(key) 让不同但可字符串化的 key 具有一致的排序和输出形式。
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set)):
        normalized = [_canonicalize(item) for item in value]
        # 删除空项，随后利用规范 JSON 字符串同时完成去重和稳定排序。
        normalized = [item for item in normalized if item is not None]
        unique = {
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")): item
            for item in normalized
        }
        ordered = [unique[key] for key in sorted(unique)]
        return ordered if ordered else None
    if isinstance(value, str):
        # 用户输入前后空格不参与缓存键；纯空白字符串与未传值等价。
        normalized = value.strip()
        return normalized if normalized else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def canonical_params_hash(params: Mapping[str, Any]) -> str:
    """返回查询参数的 SHA-256 指纹，用作缓存键的参数部分。"""
    canonical = _canonicalize(params)
    # 紧凑 JSON 去掉无意义空白，sort_keys 为嵌套字典提供确定性输出。
    serialized = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _is_empty_payload(value: Any) -> bool:
    """识别需要使用较短 TTL 的空查询结果。"""
    if value is None or value == [] or value == {}:
        return True
    if isinstance(value, Mapping) and isinstance(value.get("items"), list):
        return not value["items"]
    return False


class CacheService:
    """适用于 FastAPI 同步路由的小型 Cache-Aside 服务。"""

    def __init__(self, client_provider: Callable[[], Any] = get_cache_client):
        # 注入 provider 而非固定客户端，既能延迟创建 Redis，也方便单元测试传入 FakeRedis。
        self._client_provider = client_provider

    def _key_prefix(self) -> str:
        """构造环境隔离且可整体升级的键前缀。"""
        # APP_ENV 防止开发/生产互相污染；修改 v1 可一次性让旧结构全部失效。
        return f"{settings.CACHE_KEY_PREFIX}:{settings.APP_ENV}:page-cache:v1"

    def build_key(self, namespace: str, params: Mapping[str, Any]) -> tuple[str, str]:
        """返回完整 Redis key 和单独的参数指纹。"""
        params_hash = canonical_params_hash(params)
        return f"{self._key_prefix()}:{namespace}:{params_hash}", params_hash

    @staticmethod
    def _jittered_ttl(ttl_seconds: int) -> int:
        """给 TTL 添加可配置的随机抖动，避免大量 key 同时过期。"""
        # 防御错误配置：抖动最小为 0%，最大限制为 50%。
        percent = max(0, min(settings.CACHE_TTL_JITTER_PERCENT, 50))
        if not percent:
            return max(1, ttl_seconds)
        spread = ttl_seconds * percent / 100
        return max(1, round(random.uniform(ttl_seconds - spread, ttl_seconds + spread)))

    @staticmethod
    def _decode_payload(raw: Any) -> Any:
        """把 Redis 返回的 bytes/str 解码为 Python JSON 值。"""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    @staticmethod
    def _serialize_payload(value: Any) -> bytes:
        """把日期、Decimal、Pydantic 对象等转换为紧凑 UTF-8 JSON。"""
        # FastAPI 的编码器比直接 json.dumps 更适合接口返回值的数据类型。
        encoded = jsonable_encoder(value)
        return json.dumps(
            encoded,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _read(self, client: Any, key: str) -> tuple[bool, Any, int, int]:
        """读取并解码缓存，返回（是否命中、值、剩余 TTL、字节数）。"""
        raw = client.get(key)
        if raw is None:
            return False, None, 0, 0
        value = self._decode_payload(raw)
        ttl = int(client.ttl(key) or 0)
        value_bytes = len(raw) if isinstance(raw, bytes) else len(str(raw).encode("utf-8"))
        return True, value, max(0, ttl), value_bytes

    def _payload_size(self, value: Any) -> int:
        """尽力估算日志中的 JSON 字节数；无法序列化时返回 -1。"""
        try:
            return len(self._serialize_payload(value))
        except Exception:
            return -1

    def _write(self, client: Any, key: str, value: Any, ttl_seconds: int) -> tuple[bool, int, int]:
        """写入带过期时间的 JSON；超出大小上限时跳过缓存。"""
        serialized = self._serialize_payload(value)
        value_bytes = len(serialized)
        # 防止少数超大响应挤占 Redis 内存并造成网络延迟。
        if value_bytes > settings.CACHE_VALUE_MAX_BYTES:
            logger.warning(
                "cache_value_too_large key=%s bytes=%d max_bytes=%d",
                key,
                value_bytes,
                settings.CACHE_VALUE_MAX_BYTES,
            )
            return False, 0, value_bytes
        ttl = self._jittered_ttl(ttl_seconds)
        # ex 使用秒级 TTL，确保页面缓存最终自动失效。
        client.set(key, serialized, ex=ttl)
        return True, ttl, value_bytes

    def get_or_load_json(
        self,
        namespace: str,
        params: Mapping[str, Any],
        ttl_seconds: int,
        loader: Callable[[], Any],
        *,
        cacheable: bool = True,
        empty_ttl_seconds: Optional[int] = None,
        endpoint: Optional[str] = None,
    ) -> CacheResult:
        """优先返回缓存 JSON，未命中时调用 ``loader``，Redis 异常时自动降级。

        Args:
            namespace: 业务命名空间，例如 ``customer:filter-options``。
            params: 决定查询结果的全部参数，用于生成稳定缓存键。
            ttl_seconds: 正常结果的基础 TTL（写入时会增加随机抖动）。
            loader: 缓存不可用或未命中时执行的数据源查询函数。
            cacheable: 当前请求是否允许缓存；为 False 时直接执行 loader。
            empty_ttl_seconds: 空结果专用的较短 TTL，用于降低缓存穿透风险。
            endpoint: 仅用于日志展示的接口名称。

        Returns:
            包含业务值、缓存状态、TTL 和参数指纹的 ``CacheResult``。

        Raises:
            loader 自身抛出的异常会原样向上传递；只有 Redis 异常会被降级处理。
        """
        key, params_hash = self.build_key(namespace, params)
        started_at = time.perf_counter()
        endpoint_name = endpoint or namespace

        # 保存 loader 的执行状态和耗时。若“查库成功、写缓存失败”，外层异常处理可
        # 直接返回已加载的值，不会为了降级再查询一次数据库。
        loaded_value: Any = _MISSING
        loader_failed = False
        loader_ms = 0.0
        cache_ms = 0.0

        def load_value() -> Any:
            """执行一次业务 loader，同时收集缓存阶段与数据源阶段耗时。"""
            nonlocal loaded_value, loader_failed, loader_ms, cache_ms
            load_started = time.perf_counter()
            cache_ms = (load_started - started_at) * 1000
            try:
                loaded_value = loader()
                return loaded_value
            except Exception:
                # 标记为数据源异常，使外层 except 不会将其伪装成 Redis 降级。
                loader_failed = True
                raise
            finally:
                loader_ms = (time.perf_counter() - load_started) * 1000

        # 阶段 1：业务明确不缓存，或全局缓存开关关闭，直接旁路 Redis。
        if not cacheable or not settings.CACHE_ENABLED:
            value = load_value()
            logger.info(
                "cache_request endpoint=%s namespace=%s status=BYPASS cache_ms=%.2f "
                "db_ms=%.2f bytes=%d params_hash=%s",
                endpoint_name,
                namespace,
                cache_ms,
                loader_ms,
                self._payload_size(value),
                params_hash,
            )
            return CacheResult(value, "BYPASS", params_hash=params_hash)

        try:
            # provider 可能返回 None（缓存关闭），也可能在创建客户端时抛出连接异常。
            client = self._client_provider()
            if client is None:
                value = load_value()
                logger.info(
                    "cache_request endpoint=%s namespace=%s status=BYPASS cache_ms=%.2f "
                    "db_ms=%.2f bytes=%d params_hash=%s",
                    endpoint_name,
                    namespace,
                    cache_ms,
                    loader_ms,
                    self._payload_size(value),
                    params_hash,
                )
                return CacheResult(value, "BYPASS", params_hash=params_hash)

            # 阶段 2：先读 Redis。命中后无需执行 loader。
            try:
                hit, value, ttl, value_bytes = self._read(client, key)
                if hit:
                    logger.info(
                        "cache_request endpoint=%s namespace=%s status=HIT cache_ms=%.2f "
                        "db_ms=0.00 bytes=%d params_hash=%s",
                        endpoint_name,
                        namespace,
                        (time.perf_counter() - started_at) * 1000,
                        value_bytes,
                        params_hash,
                    )
                    return CacheResult(value, "HIT", ttl, params_hash)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
                # 无法解析的旧值/脏值不能继续使用；尽力删除后按未命中重建。
                logger.warning("Invalid cached JSON key=%s: %s", key, exc)
                try:
                    client.delete(key)
                except Exception:
                    pass

            # 阶段 3：缓存未命中。使用数据 key 的哈希创建短时互斥锁，避免同一个
            # 热点查询在过期瞬间并发打到数据库。token 用于安全释放锁。
            token = uuid.uuid4().hex
            lock_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
            lock_key = f"{self._key_prefix()}:lock:{lock_hash}"
            acquired = bool(
                # NX=仅当 key 不存在时设置；PX=锁自动过期的毫秒数，防止死锁。
                client.set(lock_key, token.encode("ascii"), nx=True, px=settings.CACHE_LOCK_TTL_MS)
            )

            if not acquired:
                # 另一个请求正在加载。短暂轮询它即将写入的结果，最多等待约 500ms。
                for _ in range(5):
                    time.sleep(0.1)
                    hit, value, ttl, value_bytes = self._read(client, key)
                    if hit:
                        logger.info(
                            "cache_request endpoint=%s namespace=%s status=HIT cache_ms=%.2f "
                            "db_ms=0.00 bytes=%d params_hash=%s waited=true",
                            endpoint_name,
                            namespace,
                            (time.perf_counter() - started_at) * 1000,
                            value_bytes,
                            params_hash,
                        )
                        return CacheResult(value, "HIT", ttl, params_hash)

                # 等待超时后优先保证接口响应：自行查库，但不写缓存，以免与锁持有者
                # 的回填发生竞争。短时间内可能多一次查询，这是可用性与保护性的折中。
                value = load_value()
                logger.info(
                    "cache_request endpoint=%s namespace=%s status=MISS cache_ms=%.2f "
                    "db_ms=%.2f bytes=%d params_hash=%s lock_timeout=true",
                    endpoint_name,
                    namespace,
                    cache_ms,
                    loader_ms,
                    self._payload_size(value),
                    params_hash,
                )
                return CacheResult(value, "MISS", params_hash=params_hash)

            try:
                # 阶段 4：当前请求持有锁，负责加载数据并回填 Redis。
                value = load_value()
                # 空列表/空字典使用较短 TTL，既避免反复查不存在的数据，也避免将
                # 暂时为空的结果缓存太久。
                effective_ttl = (
                    empty_ttl_seconds
                    if empty_ttl_seconds is not None and _is_empty_payload(value)
                    else ttl_seconds
                )
                stored, ttl, value_bytes = self._write(client, key, value, effective_ttl)
                # 数据过大时 _write 主动跳过写入，因此状态是 BYPASS 而不是 MISS。
                status = "MISS" if stored else "BYPASS"
                logger.info(
                    "cache_request endpoint=%s namespace=%s status=%s cache_ms=%.2f "
                    "db_ms=%.2f bytes=%d params_hash=%s",
                    endpoint_name,
                    namespace,
                    status,
                    cache_ms,
                    loader_ms,
                    value_bytes,
                    params_hash,
                )
                return CacheResult(value, status, ttl, params_hash)
            finally:
                # 无论 loader 或写缓存是否成功，都尽力释放自己持有的锁。
                try:
                    client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token.encode("ascii"))
                except Exception as exc:
                    logger.warning("Failed to release cache lock key=%s: %s", lock_key, exc)
        except Exception as exc:
            # loader 是业务数据源，失败必须正常抛出；不能伪装成一次缓存故障。
            if loader_failed:
                raise

            # Redis 读写失败时 fail-open。若 loader 已成功执行就复用其结果，否则现在
            # 执行一次 loader，确保缓存故障不会让业务接口不可用或重复查询数据库。
            value = loaded_value if loaded_value is not _MISSING else load_value()
            logger.warning(
                "cache_request endpoint=%s namespace=%s status=ERROR cache_ms=%.2f "
                "db_ms=%.2f bytes=%d params_hash=%s error=%s",
                endpoint_name,
                namespace,
                cache_ms or (time.perf_counter() - started_at) * 1000,
                loader_ms,
                self._payload_size(value),
                params_hash,
                exc,
            )
            return CacheResult(value, "ERROR", params_hash=params_hash)


# 默认共享服务，业务路由通常直接导入该实例，不需要自行管理 Redis 客户端。
cache_service = CacheService()
