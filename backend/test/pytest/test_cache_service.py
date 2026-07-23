"""Unit tests for the Redis cache-aside layer (no external Redis required)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.cache.service import CacheService, canonical_params_hash
from app.config import settings


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expires = {}
        self.lock = threading.Lock()
        self.fail_data_write = False

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
            if ex is not None and self.fail_data_write:
                raise ConnectionError("simulated write failure")
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

    def eval(self, _script, _key_count, key, token):
        with self.lock:
            if self.values.get(key) != token:
                return 0
            self.values.pop(key, None)
            self.expires.pop(key, None)
            return 1


def _enabled_cache(monkeypatch, fake=None):
    fake = fake or FakeRedis()
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_TTL_JITTER_PERCENT", 0)
    monkeypatch.setattr(settings, "CACHE_VALUE_MAX_BYTES", 1024 * 1024)
    monkeypatch.setattr(settings, "CACHE_LOCK_TTL_MS", 15000)
    return CacheService(lambda: fake), fake


def test_canonical_hash_normalizes_array_order_duplicates_and_empty_strings():
    left = canonical_params_hash({
        "projects": ["重客", "企业彩光ICT", "重客"],
        "owner": " ",
        "regions": [],
    })
    right = canonical_params_hash({
        "owner": None,
        "projects": ["企业彩光ICT", "重客"],
        "regions": None,
    })
    assert left == right


def test_cache_miss_then_hit_calls_loader_once(monkeypatch):
    cache, _ = _enabled_cache(monkeypatch)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"items": ["A"]}

    miss = cache.get_or_load_json("customer:test", {"p": [2, 1]}, 120, loader)
    hit = cache.get_or_load_json("customer:test", {"p": [1, 2]}, 120, loader)

    assert miss.status == "MISS"
    assert hit.status == "HIT"
    assert hit.value == {"items": ["A"]}
    assert calls == 1


def test_cache_corrupt_json_is_deleted_and_reloaded(monkeypatch):
    cache, fake = _enabled_cache(monkeypatch)
    key, _ = cache.build_key("customer:test", {"p": 1})
    fake.values[key] = b"{broken"
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"ok": True}

    result = cache.get_or_load_json("customer:test", {"p": 1}, 120, loader)

    assert result.status == "MISS"
    assert result.value == {"ok": True}
    assert calls == 1


def test_cache_write_failure_fails_open_without_reloading(monkeypatch):
    fake = FakeRedis()
    fake.fail_data_write = True
    cache, _ = _enabled_cache(monkeypatch, fake)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"ok": True}

    result = cache.get_or_load_json("customer:test", {"p": 1}, 120, loader)

    assert result.status == "ERROR"
    assert result.value == {"ok": True}
    assert calls == 1


def test_cache_connection_failure_fails_open(monkeypatch):
    def unavailable_client():
        raise TimeoutError("simulated Redis timeout")

    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    cache = CacheService(unavailable_client)
    result = cache.get_or_load_json(
        "customer:test",
        {"p": 1},
        120,
        lambda: {"ok": True},
    )

    assert result.status == "ERROR"
    assert result.value == {"ok": True}


def test_loader_failure_is_not_retried_or_hidden(monkeypatch):
    cache, _ = _enabled_cache(monkeypatch)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        cache.get_or_load_json("customer:test", {"p": 1}, 120, loader)

    assert calls == 1


def test_oversized_value_is_returned_but_not_cached(monkeypatch):
    cache, fake = _enabled_cache(monkeypatch)
    monkeypatch.setattr(settings, "CACHE_VALUE_MAX_BYTES", 10)

    result = cache.get_or_load_json(
        "customer:test",
        {"p": 1},
        120,
        lambda: {"payload": "larger-than-limit"},
    )

    data_keys = [key for key in fake.values if ":lock:" not in key]
    assert result.status == "BYPASS"
    assert data_keys == []


def test_concurrent_miss_uses_one_primary_loader(monkeypatch):
    cache, _ = _enabled_cache(monkeypatch)
    calls = 0
    calls_lock = threading.Lock()

    def loader():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.2)
        return {"items": ["A"]}

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _index: cache.get_or_load_json("customer:test", {"p": 1}, 120, loader),
            range(2),
        ))

    assert calls == 1
    assert {result.status for result in results} == {"MISS", "HIT"}
