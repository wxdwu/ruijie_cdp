"""营销看板 generation 缓存单测，不依赖真实 Redis/MySQL。"""

from __future__ import annotations

import threading
import time

import app.cache.campaign_cache as campaign_cache_module
from app.cache.campaign_cache import (
    ACTIVE_GENERATION_KEY,
    GENERATION_SEQUENCE_KEY,
    WARMING_GENERATION_KEY,
    CampaignCacheCoordinator,
)
from app.cache.service import CacheService
from app.config import settings
from app.services.etl.cache_refresh import schedule_campaign_cache_refresh


class ControlRedis:
    """覆盖通用 CacheService 与 generation Lua 所需的最小 Redis 行为。"""

    def __init__(self, *, active_generation: int | None = 1):
        self.values = {}
        self.expires = {}
        self.lock = threading.RLock()
        if active_generation is not None:
            self.values[ACTIVE_GENERATION_KEY] = str(active_generation).encode()
            self.values[GENERATION_SEQUENCE_KEY] = str(active_generation).encode()

    def _purge(self, key):
        expires_at = self.expires.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self.values.pop(key, None)
            self.expires.pop(key, None)

    def get(self, key):
        with self.lock:
            self._purge(key)
            return self.values.get(key)

    def set(self, key, value, ex=None, nx=False, px=None):
        with self.lock:
            self._purge(key)
            if nx and key in self.values:
                return False
            if isinstance(value, int):
                value = str(value).encode()
            self.values[key] = value
            if ex is not None:
                self.expires[key] = time.monotonic() + ex
            elif px is not None:
                self.expires[key] = time.monotonic() + px / 1000
            return True

    def ttl(self, key):
        with self.lock:
            self._purge(key)
            if key not in self.values:
                return -2
            if key not in self.expires:
                return -1
            return max(0, int(self.expires[key] - time.monotonic()))

    def delete(self, key):
        with self.lock:
            existed = key in self.values
            self.values.pop(key, None)
            self.expires.pop(key, None)
            return int(existed)

    def incr(self, key):
        with self.lock:
            value = int((self.values.get(key) or b"0").decode()) + 1
            self.values[key] = str(value).encode()
            return value

    def eval(self, script, key_count, *args):
        with self.lock:
            keys = args[:key_count]
            argv = args[key_count:]
            if "local active" in script:
                active = self.values.get(keys[0])
                if active is not None:
                    sequence = int((self.values.get(keys[1]) or b"0").decode())
                    if sequence < int(active.decode()):
                        self.values[keys[1]] = active
                    return [active, 0]
                generation = self.incr(keys[1])
                encoded = str(generation).encode()
                self.values[keys[0]] = encoded
                return [encoded, 1]
            if "tonumber(ARGV[1])" in script and "ARGV[2]" not in script:
                current = self.values.get(keys[0])
                expected = int(argv[0])
                if current is not None and int(current.decode()) == expected:
                    return self.delete(keys[0])
                return 0
            if "local warming" in script and "ARGV[2]" not in script:
                warming = self.values.get(keys[0])
                if warming is not None:
                    return [warming, 0]
                generation = self.incr(keys[1])
                encoded = str(generation).encode()
                self.values[keys[0]] = encoded
                return [encoded, 1]
            if "ARGV[2] == '1'" in script:
                warming = self.values.get(keys[0])
                generation = int(argv[0])
                if warming is None or int(warming.decode()) != generation:
                    return 0
                if str(argv[1]) == "1":
                    self.values[keys[1]] = str(generation).encode()
                self.delete(keys[0])
                return 1
            # 通用 CacheService 的安全解锁脚本。
            if self.values.get(keys[0]) != argv[0]:
                return 0
            return self.delete(keys[0])


def _coordinator(monkeypatch, redis=None):
    redis = redis or ControlRedis()
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_TTL_JITTER_PERCENT", 0)
    monkeypatch.setattr(settings, "CACHE_VALUE_MAX_BYTES", 1024 * 1024)
    cache = CacheService(lambda: redis)
    coordinator = CampaignCacheCoordinator(
        cache=cache,
        client_provider=lambda: redis,
        retry_delays_seconds=(),
    )
    return coordinator, redis


def test_overview_miss_then_hit_uses_same_generation(monkeypatch):
    coordinator, _ = _coordinator(monkeypatch)
    calls = 0

    def load_overview(_db, **_kwargs):
        nonlocal calls
        calls += 1
        return {"kpis": {"total_customers": 2}, "content_effect": {"deferred": True}}

    monkeypatch.setattr(campaign_cache_module, "get_campaign_overview", load_overview)

    first = coordinator.get_overview(object(), campaign_tag="C1", include_content=False)
    second = coordinator.get_overview(object(), campaign_tag="C1", include_content=False)

    assert first.status == "MISS"
    assert second.status == "HIT"
    assert first.generation == second.generation == 1
    assert second.value["kpis"]["total_customers"] == 2
    assert calls == 1


def test_customer_keyword_always_bypasses_cache(monkeypatch):
    coordinator, redis = _coordinator(monkeypatch)
    calls = 0

    def load_customers(_db, **_kwargs):
        nonlocal calls
        calls += 1
        return {"flat": [], "total": 0, "page": 1, "page_size": 10, "total_pages": 1}

    monkeypatch.setattr(campaign_cache_module, "get_customers_by_stage", load_customers)

    first = coordinator.get_customers_by_stage(object(), keyword="客户")
    second = coordinator.get_customers_by_stage(object(), keyword="客户")

    assert first.status == second.status == "BYPASS"
    assert calls == 2
    assert not any("customers-by-stage" in key for key in redis.values)


def test_default_bootstrap_caches_complete_content_and_custom_request_does_not(
    monkeypatch,
):
    coordinator, redis = _coordinator(monkeypatch)
    calls = {"filters": 0, "overview": 0, "customers": 0, "content": 0}

    def load_filters(_db):
        calls["filters"] += 1
        return {
            "campaigns": ["C1", "重客"],
            "industries": [],
            "channels": [],
            "min_date": "2026-01-01",
            "max_date": "2026-07-23",
        }

    def load_overview(_db, **_kwargs):
        calls["overview"] += 1
        return {"kpis": {}, "content_effect": {"data": [], "deferred": True}}

    def load_customers(_db, **_kwargs):
        calls["customers"] += 1
        return {"flat": [], "total": 0, "page": 1, "page_size": 10, "total_pages": 1}

    def load_content(_db, **_kwargs):
        calls["content"] += 1
        return {"data": [{"content": "白皮书"}], "help_key": "content_effect"}

    monkeypatch.setattr(campaign_cache_module, "get_filter_options", load_filters)
    monkeypatch.setattr(campaign_cache_module, "get_campaign_overview", load_overview)
    monkeypatch.setattr(campaign_cache_module, "get_customers_by_stage", load_customers)
    monkeypatch.setattr(campaign_cache_module, "get_content_effect", load_content)

    first = coordinator.get_bootstrap(object())
    second = coordinator.get_bootstrap(object())

    assert first.status == "MISS"
    assert second.status == "HIT"
    assert second.value["overview"]["content_effect"]["data"][0]["content"] == "白皮书"
    assert calls == {"filters": 1, "overview": 1, "customers": 1, "content": 1}

    custom = coordinator.get_bootstrap(object(), campaign_tag="C2")
    assert custom.status == "BYPASS"
    bootstrap_keys = [
        key
        for key in redis.values
        if "campaign:g1:bootstrap" in key and ":lock:" not in key
    ]
    assert len(bootstrap_keys) == 1


def test_new_generation_is_invisible_until_complete(monkeypatch):
    coordinator, redis = _coordinator(monkeypatch)

    target, needs_followup = coordinator._prepare_refresh_target()

    assert target == 2
    assert needs_followup is False
    assert int(redis.get(ACTIVE_GENERATION_KEY)) == 1
    assert int(redis.get(WARMING_GENERATION_KEY)) == 2

    coordinator._complete_generation(target)

    assert int(redis.get(ACTIVE_GENERATION_KEY)) == 2
    assert redis.get(WARMING_GENERATION_KEY) is None


def test_failed_warm_keeps_old_generation_and_marks_degraded(monkeypatch):
    coordinator, redis = _coordinator(monkeypatch)
    target, _ = coordinator._prepare_refresh_target()
    monkeypatch.setattr(
        coordinator,
        "_warm_once",
        lambda _generation: (_ for _ in ()).throw(RuntimeError("db failed")),
    )

    assert coordinator._warm_with_retries(target, "test") is False
    assert int(redis.get(ACTIVE_GENERATION_KEY)) == 1
    assert redis.get(WARMING_GENERATION_KEY) is None
    assert coordinator.get_status()["status"] == "degraded"


def test_empty_redis_initializes_generation_one(monkeypatch):
    coordinator, redis = _coordinator(
        monkeypatch,
        redis=ControlRedis(active_generation=None),
    )

    generation, created = coordinator._ensure_active_generation()

    assert generation == 1
    assert created is True
    assert int(redis.get(ACTIVE_GENERATION_KEY)) == 1


def test_etl_success_notification_schedules_generation_refresh(monkeypatch):
    reasons = []
    monkeypatch.setattr(
        campaign_cache_module.campaign_cache_coordinator,
        "schedule_generation_refresh",
        lambda reason: reasons.append(reason) or True,
    )

    assert schedule_campaign_cache_refresh("incremental") is True
    assert reasons == ["etl-incremental-success"]
