"""营销看板的分层缓存、generation 协调与后台预热。

Redis 中的 active generation 始终代表对外可见的数据快照。ETL 完成后，新
generation 会在后台按顺序写满默认筛选、概览、客户页、内容效果和 bootstrap，
全部成功后才原子切换；任何 Redis 或预热异常都不会阻断数据库查询。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.cache.client import get_cache_client
from app.cache.service import CacheResult, CacheService, cache_service
from app.config import settings
from app.database.engine import get_session_factory
from app.services.campaign.campaign_service import (
    get_campaign_overview,
    get_content_effect,
    get_customers_by_stage,
    get_filter_options,
)

logger = logging.getLogger(__name__)

ACTIVE_GENERATION_KEY = "campaign-cache:active-generation"
GENERATION_SEQUENCE_KEY = "campaign-cache:generation-sequence"
WARMING_GENERATION_KEY = "campaign-cache:warming-generation"

FILTER_OPTIONS_TTL_SECONDS = 14 * 60 * 60
BOOTSTRAP_TTL_SECONDS = 14 * 60 * 60
OVERVIEW_TTL_SECONDS = 30 * 60
CONTENT_TTL_SECONDS = 30 * 60
CUSTOMERS_TTL_SECONDS = 5 * 60
PREWARM_TTL_SECONDS = 14 * 60 * 60

CAMPAIGN_LOCK_TTL_MS = 60_000
CAMPAIGN_LOCK_WAIT_TIMEOUT_MS = 25_000
CAMPAIGN_LOCK_POLL_INTERVAL_MS = 100

_INITIALIZE_GENERATION_SCRIPT = """
local active = redis.call('get', KEYS[1])
if active then
    local sequence = redis.call('get', KEYS[2])
    if (not sequence) or (tonumber(sequence) < tonumber(active)) then
        redis.call('set', KEYS[2], active)
    end
    return {active, 0}
end
local generation = redis.call('incr', KEYS[2])
redis.call('set', KEYS[1], generation)
return {generation, 1}
"""

_ALLOCATE_GENERATION_SCRIPT = """
local warming = redis.call('get', KEYS[1])
if warming then
    return {warming, 0}
end
local generation = redis.call('incr', KEYS[2])
redis.call('set', KEYS[1], generation)
return {generation, 1}
"""

_COMPLETE_GENERATION_SCRIPT = """
local warming = redis.call('get', KEYS[1])
if (not warming) or (tonumber(warming) ~= tonumber(ARGV[1])) then
    return 0
end
if ARGV[2] == '1' then
    redis.call('set', KEYS[2], ARGV[1])
end
redis.call('del', KEYS[1])
return 1
"""

_CLEAR_WARMING_SCRIPT = """
local warming = redis.call('get', KEYS[1])
if warming and tonumber(warming) == tonumber(ARGV[1]) then
    return redis.call('del', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class CampaignCacheResult:
    """营销接口返回值及用于响应头的缓存元数据。"""

    value: Any
    status: str
    ttl_seconds: int
    generation: int


def _int_value(value: Any) -> int:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    return int(value or 0)


def _is_blank(value: Optional[str]) -> bool:
    return value is None or not value.strip()


def _default_campaign(filter_options: dict[str, Any]) -> Optional[str]:
    """默认使用常规专项；仅有虚拟“重客”选项时保持全量口径。"""
    return next(
        (
            campaign
            for campaign in filter_options.get("campaigns", [])
            if campaign and campaign != "重客"
        ),
        None,
    )


def _wrap(result: CacheResult, generation: int) -> CampaignCacheResult:
    return CampaignCacheResult(
        value=result.value,
        status=result.status,
        ttl_seconds=result.ttl_seconds,
        generation=generation,
    )


def apply_campaign_cache_headers(response: Any, result: CampaignCacheResult) -> None:
    """把统一缓存观测信息写入 FastAPI Response。"""
    response.headers["X-Cache"] = result.status
    response.headers["X-Cache-TTL"] = str(max(0, result.ttl_seconds))
    response.headers["X-Data-Generation"] = str(result.generation)


class CampaignCacheCoordinator:
    """组合营销子缓存，并管理可原子切换的 generation。"""

    def __init__(
        self,
        cache: CacheService = cache_service,
        client_provider: Callable[[], Any] = get_cache_client,
        session_factory_provider: Callable[[], Any] = get_session_factory,
        retry_delays_seconds: tuple[float, ...] = (30, 120, 300),
    ):
        self._cache = cache
        self._client_provider = client_provider
        self._session_factory_provider = session_factory_provider
        self._retry_delays_seconds = retry_delays_seconds
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._warm_thread: Optional[threading.Thread] = None
        self._pending_refresh = False
        self._status = "ready"
        self._last_warm_at: Optional[str] = None
        self._last_warm_ms: Optional[int] = None

    def _client(self) -> Any:
        client = self._client_provider()
        if client is None:
            raise RuntimeError("Redis cache is disabled")
        return client

    def _ensure_active_generation(self) -> tuple[int, bool]:
        if not settings.CACHE_ENABLED:
            return 0, False
        result = self._client().eval(
            _INITIALIZE_GENERATION_SCRIPT,
            2,
            ACTIVE_GENERATION_KEY,
            GENERATION_SEQUENCE_KEY,
        )
        return _int_value(result[0]), bool(_int_value(result[1]))

    def get_active_generation(self) -> int:
        """读取或初始化 generation；失败时返回 0 表示直接使用数据库。"""
        try:
            generation, created = self._ensure_active_generation()
            if created:
                logger.info("campaign_cache generation_initialized generation=%d", generation)
                self.schedule_startup_warm(reason="first-request")
            return generation
        except Exception as exc:
            logger.warning("campaign_cache generation_read_failed error=%s", exc)
            with self._state_lock:
                self._status = "degraded"
            return 0

    def _generation(self, generation: Optional[int]) -> int:
        return self.get_active_generation() if generation is None else generation

    @staticmethod
    def _namespace(generation: int, item: str) -> str:
        return f"campaign:g{generation}:{item}"

    @staticmethod
    def _cache_kwargs() -> dict[str, int]:
        return {
            "lock_ttl_ms": CAMPAIGN_LOCK_TTL_MS,
            "lock_wait_timeout_ms": CAMPAIGN_LOCK_WAIT_TIMEOUT_MS,
            "lock_poll_interval_ms": CAMPAIGN_LOCK_POLL_INTERVAL_MS,
        }

    def get_filter_options(
        self,
        db: Any,
        *,
        generation: Optional[int] = None,
        ttl_seconds: int = FILTER_OPTIONS_TTL_SECONDS,
    ) -> CampaignCacheResult:
        resolved_generation = self._generation(generation)
        result = self._cache.get_or_load_json(
            self._namespace(resolved_generation, "filter-options"),
            {"scope": "global"},
            ttl_seconds,
            lambda: get_filter_options(db),
            cacheable=resolved_generation > 0,
            endpoint="campaign/filter-options",
            **self._cache_kwargs(),
        )
        return _wrap(result, resolved_generation)

    def get_content_effect(
        self,
        db: Any,
        *,
        campaign_tag: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        channel: Optional[str] = None,
        industry: Optional[str] = None,
        generation: Optional[int] = None,
        ttl_seconds: int = CONTENT_TTL_SECONDS,
    ) -> CampaignCacheResult:
        resolved_generation = self._generation(generation)
        params = {
            "campaign_tag": campaign_tag,
            "start_date": start_date,
            "end_date": end_date,
            "channel": channel,
            "industry": industry,
        }
        result = self._cache.get_or_load_json(
            self._namespace(resolved_generation, "content-effect"),
            params,
            ttl_seconds,
            lambda: get_content_effect(db, **params),
            cacheable=resolved_generation > 0,
            endpoint="campaign/content-effect",
            **self._cache_kwargs(),
        )
        return _wrap(result, resolved_generation)

    def get_overview(
        self,
        db: Any,
        *,
        campaign_tag: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        channel: Optional[str] = None,
        industry: Optional[str] = None,
        include_content: bool = True,
        include_global_filter_options: bool = False,
        generation: Optional[int] = None,
        ttl_seconds: int = OVERVIEW_TTL_SECONDS,
    ) -> CampaignCacheResult:
        resolved_generation = self._generation(generation)
        base_params = {
            "campaign_tag": campaign_tag,
            "start_date": start_date,
            "end_date": end_date,
            "channel": channel,
            "industry": industry,
        }
        key_params = {
            **base_params,
            "include_content": include_content,
            "include_global_filter_options": include_global_filter_options,
        }

        def loader() -> dict[str, Any]:
            overview = get_campaign_overview(
                db,
                **base_params,
                include_content=False,
                include_global_filter_options=False,
            )
            if include_content:
                overview["content_effect"] = self.get_content_effect(
                    db,
                    **base_params,
                    generation=resolved_generation,
                    ttl_seconds=ttl_seconds,
                ).value
            if include_global_filter_options:
                options = self.get_filter_options(
                    db,
                    generation=resolved_generation,
                ).value
                overview["global_filter_options"] = {
                    "campaigns": options.get("campaigns", []),
                    "industries": options.get("industries", []),
                    "channels": options.get("channels", []),
                }
            return overview

        result = self._cache.get_or_load_json(
            self._namespace(resolved_generation, "overview"),
            key_params,
            ttl_seconds,
            loader,
            cacheable=resolved_generation > 0,
            endpoint="campaign/overview",
            **self._cache_kwargs(),
        )
        return _wrap(result, resolved_generation)

    def get_customers_by_stage(
        self,
        db: Any,
        *,
        campaign_tag: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        channel: Optional[str] = None,
        industry: Optional[str] = None,
        stage: Optional[str] = None,
        owner: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        include_filter_options: bool = True,
        generation: Optional[int] = None,
        ttl_seconds: int = CUSTOMERS_TTL_SECONDS,
    ) -> CampaignCacheResult:
        resolved_generation = self._generation(generation)
        params = {
            "campaign_tag": campaign_tag,
            "start_date": start_date,
            "end_date": end_date,
            "channel": channel,
            "industry": industry,
            "stage": stage,
            "owner": owner,
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "include_filter_options": include_filter_options,
        }
        result = self._cache.get_or_load_json(
            self._namespace(resolved_generation, "customers-by-stage"),
            params,
            ttl_seconds,
            lambda: get_customers_by_stage(db, **params),
            cacheable=resolved_generation > 0 and _is_blank(keyword),
            endpoint="campaign/customers-by-stage",
            **self._cache_kwargs(),
        )
        return _wrap(result, resolved_generation)

    def get_bootstrap(
        self,
        db: Any,
        *,
        campaign_tag: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        channel: Optional[str] = None,
        industry: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        generation: Optional[int] = None,
        prewarm: bool = False,
    ) -> CampaignCacheResult:
        resolved_generation = self._generation(generation)
        is_default_request = (
            all(
                _is_blank(value)
                for value in (campaign_tag, start_date, end_date, channel, industry)
            )
            and page == 1
            and page_size == 10
        )
        child_ttl = PREWARM_TTL_SECONDS if prewarm else None

        def loader() -> dict[str, Any]:
            options = self.get_filter_options(
                db,
                generation=resolved_generation,
                ttl_seconds=FILTER_OPTIONS_TTL_SECONDS,
            ).value
            applied_filters = {
                "campaign_tag": campaign_tag or _default_campaign(options),
                "start_date": start_date or options.get("min_date"),
                "end_date": end_date or options.get("max_date"),
                "channel": channel,
                "industry": industry,
            }
            overview = self.get_overview(
                db,
                **applied_filters,
                include_content=False,
                include_global_filter_options=False,
                generation=resolved_generation,
                ttl_seconds=child_ttl or OVERVIEW_TTL_SECONDS,
            ).value
            customers = self.get_customers_by_stage(
                db,
                **applied_filters,
                stage=None,
                owner=None,
                keyword=None,
                page=page,
                page_size=page_size,
                include_filter_options=False,
                generation=resolved_generation,
                ttl_seconds=child_ttl or CUSTOMERS_TTL_SECONDS,
            ).value
            overview["content_effect"] = self.get_content_effect(
                db,
                **applied_filters,
                generation=resolved_generation,
                ttl_seconds=child_ttl or CONTENT_TTL_SECONDS,
            ).value
            return {
                "filter_options": options,
                "applied_filters": applied_filters,
                "overview": overview,
                "customers": customers,
            }

        result = self._cache.get_or_load_json(
            self._namespace(resolved_generation, "bootstrap"),
            {"default": is_default_request, "page": page, "page_size": page_size},
            BOOTSTRAP_TTL_SECONDS,
            loader,
            cacheable=resolved_generation > 0 and is_default_request,
            endpoint="campaign/bootstrap",
            **self._cache_kwargs(),
        )
        return _wrap(result, resolved_generation)

    @staticmethod
    def _require_cached(result: CampaignCacheResult, item: str) -> None:
        if result.status not in {"HIT", "MISS"}:
            raise RuntimeError(f"{item} was not cached (status={result.status})")

    def _warm_once(self, generation: int) -> None:
        session = self._session_factory_provider()()
        try:
            filter_result = self.get_filter_options(
                session,
                generation=generation,
                ttl_seconds=PREWARM_TTL_SECONDS,
            )
            self._require_cached(filter_result, "filter-options")
            options = filter_result.value
            applied_filters = {
                "campaign_tag": _default_campaign(options),
                "start_date": options.get("min_date"),
                "end_date": options.get("max_date"),
                "channel": None,
                "industry": None,
            }

            overview_result = self.get_overview(
                session,
                **applied_filters,
                include_content=False,
                include_global_filter_options=False,
                generation=generation,
                ttl_seconds=PREWARM_TTL_SECONDS,
            )
            self._require_cached(overview_result, "overview")

            customers_result = self.get_customers_by_stage(
                session,
                **applied_filters,
                page=1,
                page_size=10,
                include_filter_options=False,
                generation=generation,
                ttl_seconds=PREWARM_TTL_SECONDS,
            )
            self._require_cached(customers_result, "customers-by-stage")

            content_result = self.get_content_effect(
                session,
                **applied_filters,
                generation=generation,
                ttl_seconds=PREWARM_TTL_SECONDS,
            )
            self._require_cached(content_result, "content-effect")

            bootstrap_result = self.get_bootstrap(
                session,
                page=1,
                page_size=10,
                generation=generation,
                prewarm=True,
            )
            self._require_cached(bootstrap_result, "bootstrap")
        finally:
            session.close()

    def _read_control_generation(self, key: str) -> int:
        return _int_value(self._client().get(key))

    def _prepare_startup_target(self) -> int:
        active, _ = self._ensure_active_generation()
        warming = self._read_control_generation(WARMING_GENERATION_KEY)
        if warming and warming < active:
            self._client().eval(
                _CLEAR_WARMING_SCRIPT,
                1,
                WARMING_GENERATION_KEY,
                warming,
            )
            warming = 0
        if warming:
            return warming
        self._client().set(WARMING_GENERATION_KEY, active, nx=True)
        return self._read_control_generation(WARMING_GENERATION_KEY) or active

    def _prepare_refresh_target(self) -> tuple[int, bool]:
        active, _ = self._ensure_active_generation()
        result = self._client().eval(
            _ALLOCATE_GENERATION_SCRIPT,
            2,
            WARMING_GENERATION_KEY,
            GENERATION_SEQUENCE_KEY,
        )
        target = _int_value(result[0])
        # 若命中的是尚未结束的“当前代启动预热”，完成后还需再分配一个新 generation。
        return target, target <= active

    def _complete_generation(self, generation: int) -> None:
        active = self._read_control_generation(ACTIVE_GENERATION_KEY)
        should_switch = generation > active
        completed = self._client().eval(
            _COMPLETE_GENERATION_SCRIPT,
            2,
            WARMING_GENERATION_KEY,
            ACTIVE_GENERATION_KEY,
            generation,
            "1" if should_switch else "0",
        )
        if not completed:
            raise RuntimeError(
                f"warming generation changed before completion: {generation}"
            )
        logger.info(
            "campaign_cache generation_ready generation=%d switched=%s",
            generation,
            str(should_switch).lower(),
        )

    def _clear_warming(self, generation: int) -> None:
        try:
            self._client().eval(
                _CLEAR_WARMING_SCRIPT,
                1,
                WARMING_GENERATION_KEY,
                generation,
            )
        except Exception as exc:
            logger.warning(
                "campaign_cache clear_warming_failed generation=%d error=%s",
                generation,
                exc,
            )

    def _warm_with_retries(self, generation: int, reason: str) -> bool:
        attempts = (0, *self._retry_delays_seconds)
        for attempt, delay in enumerate(attempts, start=1):
            if delay and self._stop_event.wait(delay):
                return False
            if self._stop_event.is_set():
                return False
            started_at = time.perf_counter()
            try:
                logger.info(
                    "campaign_cache warm_started generation=%d reason=%s attempt=%d",
                    generation,
                    reason,
                    attempt,
                )
                self._warm_once(generation)
                if self._stop_event.is_set():
                    return False
                self._complete_generation(generation)
                elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                with self._state_lock:
                    self._last_warm_at = datetime.now(timezone.utc).isoformat()
                    self._last_warm_ms = elapsed_ms
                    self._status = "ready"
                logger.info(
                    "campaign_cache warm_completed generation=%d reason=%s elapsed_ms=%d",
                    generation,
                    reason,
                    elapsed_ms,
                )
                return True
            except Exception as exc:
                logger.exception(
                    "campaign_cache warm_failed generation=%d reason=%s attempt=%d error=%s",
                    generation,
                    reason,
                    attempt,
                    exc,
                )
        self._clear_warming(generation)
        with self._state_lock:
            self._status = "degraded"
        return False

    def _warm_worker(self, reason: str, refresh: bool) -> None:
        allocate_new = refresh
        try:
            while not self._stop_event.is_set():
                needs_followup_generation = False
                if allocate_new:
                    generation, needs_followup_generation = (
                        self._prepare_refresh_target()
                    )
                else:
                    generation = self._prepare_startup_target()

                if generation <= 0 or not self._warm_with_retries(generation, reason):
                    break

                with self._state_lock:
                    pending_refresh = self._pending_refresh
                    self._pending_refresh = False
                if needs_followup_generation or pending_refresh:
                    allocate_new = True
                    reason = "etl-success-pending"
                    continue
                break
        except Exception as exc:
            logger.exception("campaign_cache warm_worker_failed reason=%s error=%s", reason, exc)
            with self._state_lock:
                self._status = "degraded"
        finally:
            with self._state_lock:
                self._warm_thread = None

    def _schedule(self, *, reason: str, refresh: bool) -> bool:
        if not settings.CACHE_ENABLED:
            with self._state_lock:
                self._status = "disabled"
            return False
        with self._state_lock:
            if self._warm_thread is not None and self._warm_thread.is_alive():
                if refresh:
                    self._pending_refresh = True
                logger.info(
                    "campaign_cache warm_already_running reason=%s refresh_pending=%s",
                    reason,
                    str(self._pending_refresh).lower(),
                )
                return False
            self._stop_event.clear()
            refresh = refresh or self._pending_refresh
            self._pending_refresh = False
            self._status = "warming"
            self._warm_thread = threading.Thread(
                target=self._warm_worker,
                args=(reason, refresh),
                name="campaign-cache-warm",
                daemon=True,
            )
            self._warm_thread.start()
            return True

    def schedule_startup_warm(self, reason: str = "startup") -> bool:
        """非阻塞启动当前/遗留 generation 的默认缓存预热。"""
        return self._schedule(reason=reason, refresh=False)

    def schedule_generation_refresh(self, reason: str = "etl-success") -> bool:
        """ETL 成功后非阻塞构建下一 generation。"""
        return self._schedule(reason=reason, refresh=True)

    def stop(self, timeout_seconds: float = 1.0) -> None:
        """通知后台预热停止；不会阻塞等待正在执行的数据库查询。"""
        self._stop_event.set()
        with self._state_lock:
            thread = self._warm_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0, timeout_seconds))

    def get_status(self) -> dict[str, Any]:
        """返回健康检查所需的非阻断状态。"""
        if not settings.CACHE_ENABLED:
            return {
                "status": "disabled",
                "active_generation": 0,
                "last_warm_at": self._last_warm_at,
                "last_warm_ms": self._last_warm_ms,
            }
        try:
            active = self._read_control_generation(ACTIVE_GENERATION_KEY)
            warming = self._read_control_generation(WARMING_GENERATION_KEY)
        except Exception as exc:
            logger.warning("campaign_cache status_failed error=%s", exc)
            active = 0
            warming = 0
            status = "degraded"
        else:
            with self._state_lock:
                status = self._status
                thread_running = (
                    self._warm_thread is not None and self._warm_thread.is_alive()
                )
            if warming or thread_running:
                status = "warming"
            elif status not in {"degraded", "disabled"}:
                status = "ready"
        return {
            "status": status,
            "active_generation": active,
            "warming_generation": warming or None,
            "last_warm_at": self._last_warm_at,
            "last_warm_ms": self._last_warm_ms,
        }


campaign_cache_coordinator = CampaignCacheCoordinator()
