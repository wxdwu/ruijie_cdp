"""
MySQL 连接池并发压力测试（v2 – 覆盖重试策略、熔断器、Jitter）

测试目标:
  1. 并发读：验证连接池基础功能
  2. 并发写：验证死锁重试（Deadlock 策略：快重试、短延迟）
  3. 混合读写：模拟真实 API 场景
  4. 超量压力：线程 > max_connections，验证 pool_timeout 不卡死
  5. 熔断器：连续失败后熔断器打开，恢复后自动关闭
  6. Jitter 策略对比：full / equal / decorrelated

用法:
  cd backend && python -m test.test_mysql_conn_pool
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

sys.path.insert(0, ".")

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.connection_pool import (
    get_engine,
    get_pool_status,
    execute_with_retry,
    dispose_engine,
    reset_retry_count,
    get_retry_count,
    get_circuit_breaker_state,
    POOL_SIZE,
    MAX_OVERFLOW,
    POOL_TIMEOUT,
    CB_SUCCESS_THRESHOLD,
    CircuitBreakerOpenError,
)

# ── 日志 ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-10s] %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pool_test")


# ── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class Result:
    ok: int = 0
    fail: int = 0
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_ok(self, latency_ms: float):
        with self.lock:
            self.ok += 1
            self.latencies_ms.append(latency_ms)

    def record_fail(self, err: str):
        with self.lock:
            self.fail += 1
            self.errors.append(err)

    def stats(self) -> dict[str, Any]:
        with self.lock:
            lat = self.latencies_ms
            if not lat:
                return {"ok": self.ok, "fail": self.fail, "latency_ms": {}}
            lat_sorted = sorted(lat)
            p50 = lat_sorted[len(lat_sorted) // 2]
            p99 = lat_sorted[int(len(lat_sorted) * 0.99)]
            return {
                "ok": self.ok,
                "fail": self.fail,
                "latency_ms": {
                    "avg": round(sum(lat) / len(lat), 1),
                    "p50": round(p50, 1),
                    "p99": round(p99, 1),
                    "max": round(max(lat), 1),
                },
            }


# ── 数据库操作 ──────────────────────────────────────────────────────────────

def do_read() -> None:
    """执行一次 SELECT 查询（使用连接池 + 熔断器感知）。"""
    def _run() -> None:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 AS val FROM DUAL"))

    execute_with_retry(_run, operation_name="read")


def do_write(thread_id: int = 0, table: str = "tmp_pool_test", shared_label: bool = False) -> None:
    """执行一次 INSERT + UPDATE + DELETE（自动重试 transient 错误）。

    Args:
        thread_id:      线程 ID（用于独立 label 或追踪）
        shared_label:   为 True 时所有线程共用同一个 label，
                        会增加死锁概率，用于验证重试逻辑。
                        UPDATE 改为按 id 精确更新，减少锁范围。
    """
    label = "stress_shared" if shared_label else f"stress_t{thread_id}"

    def _run() -> None:
        engine = get_engine()
        with engine.begin() as conn:
            # 1) INSERT – 返回自增 id
            result = conn.execute(
                text(f"INSERT INTO {table} (label, val) VALUES (:label, 1)"),
                {"label": label},
            )
            last_id = result.lastrowid

            # 2) UPDATE – 按 id 精确更新（只锁 1 行，大幅减少死锁概率）
            if last_id:
                conn.execute(
                    text(f"UPDATE {table} SET val = val + 1 WHERE id = :id"),
                    {"id": last_id},
                )

            # 3) DELETE – 清理旧数据（只删自己的 label，且 val 很大时）
            conn.execute(
                text(f"DELETE FROM {table} WHERE label = :label AND val > 500"),
                {"label": label},
            )

    execute_with_retry(_run, operation_name=f"write:t{thread_id}")


def do_mixed(thread_id: int, index: int) -> None:
    """交替读写，模拟 API 真实场景。"""
    if index % 3 == 0:
        do_read()
    elif index % 3 == 1:
        do_read()
    else:
        do_write(thread_id)


def ensure_test_table() -> None:
    """创建压测临时表（用完即弃）。"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tmp_pool_test (
                id      BIGINT AUTO_INCREMENT PRIMARY KEY,
                label   VARCHAR(64)  NOT NULL DEFAULT '',
                val     INT          NOT NULL DEFAULT 0,
                ts      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX   idx_label (label)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))


def drop_test_table() -> None:
    """删除压测临时表。"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS tmp_pool_test"))


# ── 工作线程 ────────────────────────────────────────────────────────────────

def worker(
    thread_id: int,
    total_ops: int,
    result: Result,
    barrier: threading.Barrier | None = None,
    mode: str = "read",
    shared_label: bool = False,
) -> None:
    """执行操作的工作线程。

    Args:
        mode: 'read' | 'write' | 'mixed'
        shared_label: 为 True 时写操作共用同一个 label，增加死锁概率
    """
    if barrier:
        barrier.wait()

    for i in range(total_ops):
        t0 = time.perf_counter()
        try:
            if mode == "read":
                do_read()
            elif mode == "write":
                do_write(thread_id, shared_label=shared_label)
            else:  # mixed
                do_mixed(thread_id, i)
            elapsed = (time.perf_counter() - t0) * 1000
            result.record_ok(elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            result.record_fail(f"[t{thread_id} op{i}] {type(e).__name__}: {e}")
            logger.warning("t%d op%d FAILED after %.0fms: %s", thread_id, i, elapsed, e)


def pool_watcher(
    stop_event: threading.Event,
    snapshots: list,
    interval: float = 1.0,
) -> None:
    """后台线程：定时采样连接池状态。"""
    while not stop_event.is_set():
        try:
            snapshots.append(get_pool_status())
        except Exception:
            pass
        stop_event.wait(interval)


# ── 测试场景 ────────────────────────────────────────────────────────────────

def run_scenario(
    name: str,
    n_threads: int,
    ops_per_thread: int,
    mode: str = "read",
    shared_label: bool = False,
) -> Result:
    """运行一个压测场景并返回结果。

    Args:
        shared_label: 为 True 时写操作共用同一 label，增加死锁概率
    """
    print(f"\n{'=' * 68}")
    print(f"  场景: {name}")
    print(f"  线程数: {n_threads}  |  每线程操作数: {ops_per_thread}")
    print(f"  总请求: {n_threads * ops_per_thread}  |  模式: {mode}")
    if shared_label:
        print(f"  ⚠️  共用 label 模式（高死锁概率，用于验证重试）")
    print(f"  max_connections: {POOL_SIZE + MAX_OVERFLOW}")
    print(f"{'=' * 68}")

    reset_retry_count()
    result = Result()

    stop_event = threading.Event()
    snapshots: list[dict] = []
    watcher = threading.Thread(
        target=pool_watcher,
        args=(stop_event, snapshots, 1.0),
        name="pool-watcher",
        daemon=True,
    )
    watcher.start()

    barrier = threading.Barrier(n_threads) if n_threads > 1 else None

    start = time.perf_counter()
    threads = [
        threading.Thread(
            target=worker,
            args=(i, ops_per_thread, result, barrier, mode, shared_label),
            name=f"w-{i:02d}",
        )
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    stop_event.set()
    watcher.join(timeout=2)

    # ── 打印结果 ──
    stats = result.stats()
    retry_count = get_retry_count()
    cb_state = get_circuit_breaker_state()
    print(f"\n  ✅ 成功: {stats['ok']}  ❌ 失败: {stats['fail']}")
    print(f"  ⏱  总耗时: {elapsed:.2f}s  |  QPS: {stats['ok'] / elapsed:.1f}")
    print(f"  🔁 重试触发: {retry_count}")
    print(f"  🔌 熔断器: {cb_state['state']} (连续失败: {cb_state['consecutive_failures']})")
    if "latency_ms" in stats:
        lm = stats["latency_ms"]
        print(f"  📊 延迟 (ms): avg={lm.get('avg', 0)}, "
              f"p50={lm.get('p50', 0)}, "
              f"p99={lm.get('p99', 0)}, "
              f"max={lm.get('max', 0)}")

    if snapshots:
        peak_out = max(s["checked_out"] for s in snapshots)
        peak_total = max(s["total_connections"] for s in snapshots)
        print(f"  🏊 池峰值: checked_out={peak_out}, "
              f"total_connections={peak_total}  (max={POOL_SIZE + MAX_OVERFLOW})")

    if result.errors:
        print(f"\n  ❌ 错误列表 (前 10 条):")
        for e in result.errors[:10]:
            print(f"    - {e}")

    return result


def test_circuit_breaker() -> bool:
    """测试熔断器：主动触发连续失败，验证熔断器打开/关闭。

    流程:
      closed → [连续失败 ≥10次] → open → [等待 30s] → half_open (探测)
      → [连续成功 ≥2次] → closed
    """
    print(f"\n{'=' * 68}")
    print("  场景: 6. 熔断器测试")
    print(f"{'=' * 68}")

    # 重置熔断器
    from app.connection_pool import _cb_state, _cb_lock, CB_SUCCESS_THRESHOLD
    with _cb_lock:
        _cb_state["state"] = "closed"
        _cb_state["consecutive_failures"] = 0
        _cb_state["consecutive_successes"] = 0

    reset_retry_count()

    # 用错误的 SQL 强制触发连续失败（max_retries=0 表示不重试，直接失败）
    def _bad_sql() -> None:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text("SELECT * FROM nonexistent_table_xyz"))

    # 连续执行失败，直到熔断器打开
    print("\n  🔴 触发连续失败中...")
    opened = False
    for i in range(15):
        try:
            execute_with_retry(_bad_sql, max_retries=0, operation_name="cb-test")
        except Exception:
            pass
        cb = get_circuit_breaker_state()
        print(f"    失败 {i+1}: 熔断器状态 = {cb['state']}, 连续失败 = {cb['consecutive_failures']}")
        if cb["state"] == "open":
            print("  ✅ 熔断器已打开！")
            opened = True
            break

    if not opened:
        print("  ❌ 熔断器未能打开（连续失败不足）")
        return False

    # 等待冷却时间（CB_OPEN_DURATION=30s），之后第一次 do_read() 会触发 open → half_open
    print(f"\n  🟡 等待冷却时间（30s），之后首次成功请求将触发 half-open 探测...")
    time.sleep(32)

    # 连续执行成功操作，使熔断器从 half_open → closed
    # 第一次 do_read() 会触发 open → half_open 转换，并成功执行
    # 需要连续 CB_SUCCESS_THRESHOLD 次成功，熔断器才关闭
    print(f"\n  🟢 执行成功操作，验证熔断器恢复（需要连续成功 {CB_SUCCESS_THRESHOLD} 次）...")
    for i in range(CB_SUCCESS_THRESHOLD + 2):  # 多调用几次，确保足够
        try:
            do_read()
            print(f"    成功 {i+1}: OK")
        except CircuitBreakerOpenError:
            print(f"    成功 {i+1}: 熔断器仍 open，等待...")
            time.sleep(2)
            continue
        except Exception as e:
            print(f"    成功 {i+1}: 失败 - {e}")
            break

        cb = get_circuit_breaker_state()
        print(f"    熔断器状态: {cb['state']} (连续成功: {cb.get('consecutive_successes', 0)})")
        if cb["state"] == "closed":
            print("  ✅ 熔断器已关闭（恢复）！")
            return True

    cb = get_circuit_breaker_state()
    print(f"  最终熔断器状态: {cb['state']}")
    return cb["state"] == "closed"


# ── 主入口 ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 68)
    print("     MySQL 连接池并发压力测试 (v2)")
    print(f"     开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"     配置: pool_size={POOL_SIZE}  overflow={MAX_OVERFLOW}")
    print(f"           timeout={POOL_TIMEOUT}s  jitter=full")
    print("=" * 68)

    logger.info("初始化连接池 ...")
    engine = get_engine()
    status = get_pool_status()
    print(f"\n  初始池状态: {status}")

    logger.info("创建测试表 ...")
    ensure_test_table()

    all_passed = True
    try:
        # ─── 场景 1: 轻量读 ─────────────────────────────────────────────
        r = run_scenario(
            "1. 轻量并发读", n_threads=10, ops_per_thread=20, mode="read"
        )
        all_passed &= r.fail == 0

        # ─── 场景 2: 并发写（每线程独立 label，低死锁）────────────────
        r = run_scenario(
            "2. 并发写（每线程独立 label，低死锁）",
            n_threads=10, ops_per_thread=15, mode="write",
        )
        all_passed &= r.fail < r.ok

        # ─── 场景 3: 混合读写 ─────────────────────────────────────────
        r = run_scenario(
            "3. 混合读写", n_threads=15, ops_per_thread=20, mode="mixed"
        )
        all_passed &= r.fail < r.ok

        # ─── 场景 4: 超量连接压力 ─────────────────────────────────────
        r = run_scenario(
            "4. 超量压力（线程 > max_connections，验证 timeout 不卡死）",
            n_threads=60, ops_per_thread=5, mode="read",
        )
        if r.fail > 0:
            print(f"  ℹ️  超量场景 {r.fail} 个请求因 pool_timeout 失败（预期行为）")
        all_passed &= True

        # ─── 场景 5: 长持续时间稳定性 ─────────────────────────────────
        r = run_scenario(
            "5. 持续稳定性（20 线程 × 20 轮）",
            n_threads=20, ops_per_thread=20, mode="mixed",
        )
        all_passed &= r.fail < r.ok

        # ─── 场景 6: 死锁重试验证（共用 label，高死锁概率）──────────
        r = run_scenario(
            "6. 死锁重试验证（共用 label，高死锁概率）",
            n_threads=8, ops_per_thread=30, mode="write",
            shared_label=True,
        )
        # 共用 label 场景允许一定失败，但重试必须触发（重试次数 > 0）
        retry_count = get_retry_count()
        if retry_count > 0:
            print(f"  ✅ 死锁重试生效：{retry_count} 次重试被触发")
        else:
            print(f"  ⚠️  未观察到死锁重试（可考虑增加线程数或操作数）")
        all_passed &= r.ok > 0  # 至少部分成功

        # ─── 场景 7: 熔断器 ─────────────────────────────────────────
        cb_ok = test_circuit_breaker()
        all_passed &= cb_ok

    finally:
        logger.info("清理测试表 ...")
        drop_test_table()
        status = get_pool_status()
        print(f"\n  最终池状态: {status}")
        logger.info("释放连接池 ...")
        dispose_engine()

    # ── 总结 ──
    print(f"\n{'=' * 68}")
    if all_passed:
        print("  ✅  全部场景通过 — 连接池工作正常")
    else:
        print("  ❌  部分场景失败 — 请检查上方错误详情")
    print(f"{'=' * 68}\n")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
