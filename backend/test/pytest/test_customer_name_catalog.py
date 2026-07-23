"""Tests for the paged Redis customer-name catalog (no real Redis required)."""

from __future__ import annotations

import time

from app.cache.customer_name_catalog import CustomerNameCatalog
from app.cache.service import CacheService
from app.config import settings


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.commands.append((name, args, kwargs))
            return self
        return queue

    def execute(self):
        return [getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.commands]


class CatalogFakeRedis:
    def __init__(self):
        self.values = {}
        self.zsets = {}
        self.expires = {}

    def _purge(self, key):
        if self.expires.get(key, float("inf")) <= time.monotonic():
            self.values.pop(key, None)
            self.zsets.pop(key, None)
            self.expires.pop(key, None)

    def get(self, key):
        self._purge(key)
        return self.values.get(key)

    def set(self, key, value, ex=None, nx=False, px=None):
        self._purge(key)
        if nx and (key in self.values or key in self.zsets):
            return False
        self.values[key] = value
        if ex is not None:
            self.expires[key] = time.monotonic() + ex
        elif px is not None:
            self.expires[key] = time.monotonic() + px / 1000
        return True

    def delete(self, key):
        existed = key in self.values or key in self.zsets
        self.values.pop(key, None)
        self.zsets.pop(key, None)
        self.expires.pop(key, None)
        return int(existed)

    def zadd(self, key, mapping):
        members = self.zsets.setdefault(key, set())
        before = len(members)
        members.update(mapping)
        return len(members) - before

    def zrange(self, key, start, stop):
        self._purge(key)
        members = sorted(self.zsets.get(key, set()))
        return members[start:stop + 1]

    def zrangebylex(self, key, minimum, maximum, start=0, num=None):
        self._purge(key)
        lower = minimum[1:]
        upper = maximum[1:]
        members = [
            member for member in sorted(self.zsets.get(key, set()))
            if member >= lower and member < upper
        ]
        return members[start:start + num] if num is not None else members[start:]

    def expire(self, key, seconds):
        if key not in self.values and key not in self.zsets:
            return False
        self.expires[key] = time.monotonic() + seconds
        return True

    def ttl(self, key):
        self._purge(key)
        if key not in self.values and key not in self.zsets:
            return -2
        return max(0, int(self.expires.get(key, time.monotonic()) - time.monotonic()))

    def rename(self, source, destination):
        self._purge(source)
        if source in self.zsets:
            self.zsets[destination] = self.zsets.pop(source)
        else:
            self.values[destination] = self.values.pop(source)
        if source in self.expires:
            self.expires[destination] = self.expires.pop(source)
        return True

    def pipeline(self, transaction=True):
        return _Pipeline(self)

    def eval(self, _script, _key_count, key, token):
        if self.values.get(key) != token:
            return 0
        return self.delete(key)


def _enabled_catalog(monkeypatch):
    fake = CatalogFakeRedis()
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_TTL_JITTER_PERCENT", 0)
    monkeypatch.setattr(settings, "CACHE_LOCK_TTL_MS", 15000)
    shared_cache = CacheService(lambda: fake)
    return CustomerNameCatalog(lambda: fake, shared_cache), fake


def test_catalog_builds_once_then_serves_browsable_pages(monkeypatch):
    catalog, _ = _enabled_catalog(monkeypatch)
    builds = 0

    def load_catalog():
        nonlocal builds
        builds += 1
        return ["丙公司", "甲公司", "乙公司", "乙公司"]

    first = catalog.get_page(
        special_project=["企业彩光ICT"],
        query="",
        offset=0,
        limit=2,
        ttl_seconds=3600,
        catalog_loader=load_catalog,
        page_loader=lambda: {"items": [], "has_more": False},
    )
    second = catalog.get_page(
        special_project=["企业彩光ICT"],
        query="",
        offset=2,
        limit=2,
        ttl_seconds=3600,
        catalog_loader=load_catalog,
        page_loader=lambda: {"items": [], "has_more": False},
    )

    assert first.status == "MISS"
    assert first.value == {"items": ["丙公司", "乙公司"], "has_more": True}
    assert second.status == "HIT"
    assert second.value == {"items": ["甲公司"], "has_more": False}
    assert builds == 1


def test_catalog_prefix_search_is_case_insensitive(monkeypatch):
    catalog, _ = _enabled_catalog(monkeypatch)
    catalog.get_page(
        special_project=["企业彩光ICT"],
        query="",
        offset=0,
        limit=10,
        ttl_seconds=3600,
        catalog_loader=lambda: ["Ruijie Networks", "RUIZHI Tech", "Other"],
        page_loader=lambda: {"items": [], "has_more": False},
    )

    result = catalog.get_page(
        special_project=["企业彩光ICT"],
        query="rui",
        offset=0,
        limit=1,
        ttl_seconds=3600,
        catalog_loader=lambda: [],
        page_loader=lambda: {"items": [], "has_more": False},
    )

    assert result.status == "HIT"
    assert result.value == {"items": ["Ruijie Networks"], "has_more": True}


def test_catalog_redis_error_falls_back_without_full_catalog_load(monkeypatch):
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    catalog = CustomerNameCatalog(
        lambda: (_ for _ in ()).throw(TimeoutError("redis unavailable")),
        CacheService(lambda: None),
    )
    full_loads = 0

    def full_loader():
        nonlocal full_loads
        full_loads += 1
        return ["不应加载"]

    result = catalog.get_page(
        special_project=["企业彩光ICT"],
        query="",
        offset=0,
        limit=50,
        ttl_seconds=3600,
        catalog_loader=full_loader,
        page_loader=lambda: {"items": ["数据库第一页"], "has_more": False},
    )

    assert result.status == "ERROR"
    assert result.value == {"items": ["数据库第一页"], "has_more": False}
    assert full_loads == 0


def test_catalog_can_return_cold_page_and_defer_full_build(monkeypatch):
    catalog, _ = _enabled_catalog(monkeypatch)
    deferred = 0
    full_loads = 0

    def schedule_build():
        nonlocal deferred
        deferred += 1

    def load_catalog():
        nonlocal full_loads
        full_loads += 1
        return ["不应同步加载"]

    result = catalog.get_page(
        special_project=["企业彩光ICT"],
        query="",
        offset=0,
        limit=50,
        ttl_seconds=3600,
        catalog_loader=load_catalog,
        page_loader=lambda: {"items": ["数据库第一页"], "has_more": True},
        defer_build=schedule_build,
    )

    assert result.status == "MISS"
    assert result.value == {"items": ["数据库第一页"], "has_more": True}
    assert deferred == 1
    assert full_loads == 0


def test_catalog_disabled_bypasses_redis(monkeypatch):
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)
    catalog = CustomerNameCatalog(lambda: None, CacheService(lambda: None))

    result = catalog.get_page(
        special_project=["企业彩光ICT"],
        query="锐捷",
        offset=0,
        limit=50,
        ttl_seconds=3600,
        catalog_loader=lambda: ["不应加载"],
        page_loader=lambda: {"items": ["锐捷网络"], "has_more": False},
    )

    assert result.status == "BYPASS"
    assert result.value["items"] == ["锐捷网络"]
