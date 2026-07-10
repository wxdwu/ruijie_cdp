"""
定时触发「表数据监控」接口的调度脚本（Windows 环境，纯标准库，无第三方依赖）。

功能：
  - 按类 Linux crontab 的时间规则，定时向监控接口发 POST 请求。
  - 默认触发：curl -s -X POST "http://localhost:8000/api/admin/monitor/run"
    本脚本用 Python 内置 urllib 实现等价请求（Windows 下无需安装 curl）。
  - 支持两类触发：
      1) 周期任务（crontab 风格，可配置多条）
      2) 一次性任务（指定绝对时间，触发一次后自动失效）

crontab 时间格式（5 个字段，空格分隔）：
  分 时 日 月 周
   - 分：0-59    时：0-23    日：1-31    月：1-12    周：0-6（0=周日）
   - 通配符  *      表示任意
   - 步长    */n    表示每 n 个单位（如 */5 = 每 5 分钟）
   - 列表    a,b,c  表示枚举（如 1,15,30）
   - 范围    a-b    表示区间（如 9-18）
   - 组合    可混用，如 "0,30 9-18 * * 1-5" 表示工作日 9-18 点间每半点触发

示例：
  "0 * * * *"          每小时整点触发一次
  "*/15 * * * *"       每 15 分钟触发一次
  "30 9 * * 1-5"       工作日（周一至周五）09:30 触发
  "0 0 1 * *"          每月 1 号 00:00 触发
  "0 2 * * 0"          每周日 02:00 触发

  注：crontab 只能整点/整分对齐，无法直接表达"从任意当前时刻起每 N 分钟"。
      若需「从脚本启动时刻起每 10 分钟」（如 3:03→3:13→3:23…），请用配置项
      INTERVAL_MINUTES = [10]（按启动时刻对齐，与墙钟无关），详见下方 DEFAULT_INTERVAL_MINUTES。



用法：
  # 以前台方式持续运行（Ctrl+C 退出）
  python monitor_scheduler.py

  # 立即触发一次并退出（用于测试接口是否可达）
  python monitor_scheduler.py --once

  # 使用自定义配置文件
  python monitor_scheduler.py --config monitor_schedule.json

Windows 常驻建议：
  - 简单方式：用 pythonw 静默运行（无控制台窗口）：
      pythonw monitor_scheduler.py
  - 生产方式：通过「任务计划程序」或 nssm 注册为 Windows 服务，开机自启。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# 默认配置（可被同目录 monitor_schedule.json 覆盖）
# ─────────────────────────────────────────────────────────────────────────────

# 要触发的接口地址（等价于 curl 示例中的 URL）
DEFAULT_URL = "http://localhost:8000/api/admin/monitor/run"

# 周期任务：crontab 风格表达式列表（默认每小时整点触发一次）
DEFAULT_SCHEDULES = [
    # "0 * * * *",              # 每小时第 0 分钟（整点）触发
     "*/10 * * * *",         # 每 10 分钟触发一次（示例，按需取消注释）
    # "30 9 * * 1-5",         # 工作日 09:30 触发（示例）
    # ── 每 10 分钟「从当前时刻」的写法（demo，按需选用其一）──
    # "3,13,23,33,43,53 * * * *",  # 偏移写死：仅当脚本恰在 :03 启动才得 :03,:13…（墙钟对齐，启动时刻变化需手改数字）
    #   说明：crontab 只能整点/整分对齐，无法表达"从任意当前时刻起每 10 分"。
    #   若要从「任意当前时刻」起每 10 分钟（如 3:03→3:13→3:23…），请用下方 INTERVAL_MINUTES = [10]
    #   （按脚本启动时刻对齐，与墙钟无关；启用后无需在此写 crontab 表达式）。
]

# 一次性任务：绝对时间字符串列表（格式 "%Y-%m-%d %H:%M:%S"），触发后自动失效
DEFAULT_ONE_SHOT = [
    # "2026-07-10 15:30:00",  # 在指定时间点触发一次（示例）
]

# 间隔触发：从「脚本启动时刻」起，每 N 分钟触发一次（与墙钟/整点无关）。
#   - 用于 "从当前时间起每 10 分钟" 这类 crontab 无法直接表达的诉求：
#       当前 3:03 启动 → 3:03、3:13、3:23 …… 触发（首触发即为启动时刻）。
#   - 留空 [] 表示不启用；填 [10] 即每 10 分钟；[5, 30] 表示同时有 5 分钟与 30 分钟两种间隔。
#   - 与上方 crontab 的 "*/10 * * * *"（整 10 分对齐）区别：后者固定 :00/:10/:20…，
#     前者跟随脚本实际启动时刻，任意时刻启动都能保证"启动后每满 N 分钟"触发。
DEFAULT_INTERVAL_MINUTES = []

# 轮询检查间隔（秒），到点时实际触发误差不超过该值
DEFAULT_CHECK_INTERVAL = 15

# 日志文件路径（与本脚本同目录）
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_scheduler.log")


# ─────────────────────────────────────────────────────────────────────────────
# crontab 表达式解析与匹配
# ─────────────────────────────────────────────────────────────────────────────

def parse_field(field: str, minimum: int, maximum: int) -> set:
    """解析单个 crontab 字段为允许的取值集合。

    支持：* 、*/n 、a-b 、a,b,c 及其组合。返回 set[int]。
    """
    result: set = set()
    field = field.strip()
    if field == "*":
        return set(range(minimum, maximum + 1))
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
        else:
            base = part
        if base == "*":
            lo, hi = minimum, maximum
        elif "-" in base:
            lo_s, hi_s = base.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
        else:
            lo = hi = int(base)
        for v in range(lo, hi + 1, step):
            if minimum <= v <= maximum:
                result.add(v)
    return result


def parse_cron(expr: str):
    """将 5 字段 crontab 表达式解析为 (分, 时, 日, 月, 周) 五个集合。"""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"非法的 crontab 表达式（应为 5 个字段）: {expr!r}")
    mins = parse_field(parts[0], 0, 59)
    hours = parse_field(parts[1], 0, 23)
    doms = parse_field(parts[2], 1, 31)
    months = parse_field(parts[3], 1, 12)
    dows = parse_field(parts[4], 0, 6)   # 0=周日 .. 6=周六
    return mins, hours, doms, months, dows


def _cron_dow(dt: datetime) -> int:
    """将 Python weekday()（周一=0..周日=6）转换为 crontab 周几（周日=0..周六=6）。"""
    return (dt.weekday() + 1) % 7


def cron_matches(cron, dt: datetime) -> bool:
    """判断给定时间 dt 是否满足 crontab 表达式 cron。

    当「日」与「周」字段同时为 * 时按常规匹配；仅其中一个受限时取该字段；
    两个都受限时按 Vixie cron 规则取「或」关系。
    """
    mins, hours, doms, months, dows = cron
    if dt.minute not in mins:
        return False
    if dt.hour not in hours:
        return False
    if dt.month not in months:
        return False

    dom_is_wild = (doms == set(range(1, 32)))
    dow_is_wild = (dows == set(range(0, 7)))

    if not dom_is_wild and not dow_is_wild:
        if dt.day not in doms and _cron_dow(dt) not in dows:
            return False
    elif not dom_is_wild:
        if dt.day not in doms:
            return False
    elif not dow_is_wild:
        if _cron_dow(dt) not in dows:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 触发请求与日志
# ─────────────────────────────────────────────────────────────────────────────

def log(message: str) -> None:
    """同时输出到控制台与日志文件。"""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def trigger(url: str) -> None:
    """向监控接口发送 POST 请求（等价于 curl -s -X POST url）。"""
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            log(f"触发成功 {url} -> HTTP {resp.status}, 响应(截断): {body[:200]}")
    except urllib.error.HTTPError as exc:
        log(f"触发失败 {url} -> HTTP {exc.code}: {exc.reason}")
    except Exception as exc:  # noqa: BLE001 - 调度器需对单次失败容错，避免进程退出
        log(f"触发异常 {url} -> {type(exc).__name__}: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 主循环
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path: str | None):
    """加载配置：返回 (url, schedules, one_shot, interval_minutes, check_interval)。"""
    url = DEFAULT_URL
    schedules = list(DEFAULT_SCHEDULES)
    one_shot = list(DEFAULT_ONE_SHOT)
    interval_minutes = list(DEFAULT_INTERVAL_MINUTES)
    check_interval = DEFAULT_CHECK_INTERVAL

    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        url = cfg.get("url", url)
        schedules = cfg.get("schedules", schedules)
        one_shot = cfg.get("one_shot", one_shot)
        interval_minutes = cfg.get("interval_minutes", interval_minutes)
        check_interval = cfg.get("check_interval", check_interval)
        log(f"已加载配置文件: {path}")
    return url, schedules, one_shot, interval_minutes, check_interval


def main() -> None:
    parser = argparse.ArgumentParser(description="定时触发表数据监控接口的调度器")
    parser.add_argument(
        "--once", action="store_true",
        help="立即触发一次并退出（用于测试接口可达性）",
    )
    parser.add_argument(
        "--config", default=None,
        help="配置文件路径（JSON），覆盖默认调度设置",
    )
    args = parser.parse_args()

    url, schedule_exprs, one_shot_exprs, interval_minutes, check_interval = load_config(args.config)

    # 预解析所有周期任务表达式
    parsed = []
    for expr in schedule_exprs:
        try:
            parsed.append((expr, parse_cron(expr)))
        except ValueError as exc:
            log(f"跳过非法调度表达式: {exc}")

    # 解析一次性任务时间
    one_shot_times = []
    for expr in one_shot_exprs:
        try:
            one_shot_times.append(datetime.strptime(expr, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            log(f"跳过非法一次性时间（需 %Y-%m-%d %H:%M:%S）: {expr!r}")

    # 解析间隔触发（分钟数需为正整数）
    interval_list = []
    for v in interval_minutes:
        try:
            n = int(v)
            if n > 0:
                interval_list.append(n)
            else:
                log(f"跳过非法间隔（需正整数分钟）: {v!r}")
        except (ValueError, TypeError):
            log(f"跳过非法间隔: {v!r}")

    log(f"目标接口: {url}")
    log(f"周期任务({len(parsed)}): " + "; ".join(e for e, _ in parsed) if parsed
        else "周期任务: 无")
    log(f"一次性任务({len(one_shot_times)}): " +
        ", ".join(t.strftime("%Y-%m-%d %H:%M:%S") for t in one_shot_times)
        if one_shot_times else "一次性任务: 无")
    log("间隔触发(自启动对齐): " + ", ".join(f"每{n}分钟" for n in interval_list)
        if interval_list else "间隔触发: 无")

    # --once：立即触发一次后退出
    if args.once:
        log("以 --once 模式运行，立即触发一次。")
        trigger(url)
        return

    log(f"调度器启动，轮询间隔 {check_interval}s。Ctrl+C 退出。")
    fired_keys: set = set()      # 已触发标记，避免同一分钟重复触发
    done_one_shot: set = set()   # 已完成的一次性任务索引
    start_time = datetime.now()  # 间隔触发的基准时刻（"从当前"语义的来源）
    # 间隔触发首个触发点即启动时刻，之后每 N 分钟递进
    interval_next = {n: start_time for n in interval_list}

    try:
        while True:
            now = datetime.now()
            minute_key = now.strftime("%Y%m%d%H%M")

            # 周期任务：匹配且本分钟尚未触发
            for idx, (expr, cron) in enumerate(parsed):
                key = f"p{idx}:{minute_key}"
                if key not in fired_keys and cron_matches(cron, now):
                    log(f"命中周期任务 [{expr}]，准备触发。")
                    trigger(url)
                    fired_keys.add(key)

            # 间隔触发：从启动时刻起每 N 分钟（与墙钟/整点无关）
            for n in interval_list:
                if now >= interval_next[n]:
                    log(f"命中间隔任务（每 {n} 分钟，自启动对齐），准备触发。")
                    trigger(url)
                    while interval_next[n] <= now:
                        interval_next[n] += timedelta(minutes=n)

            # 一次性任务：到达指定时间且尚未触发
            for idx, target in enumerate(one_shot_times):
                if idx in done_one_shot:
                    continue
                if now >= target:
                    log(f"命中一次性任务 [{target:%Y-%m-%d %H:%M:%S}]，准备触发。")
                    trigger(url)
                    done_one_shot.add(idx)

            # 清理过期的 fired 标记（仅保留当天，避免无限增长）
            if now.minute == 0 and now.hour == 0:
                fired_keys.clear()
                log("每日 00:00 清理周期任务触发标记。")

            time.sleep(check_interval)
    except KeyboardInterrupt:
        log("收到中断信号，调度器退出。")


if __name__ == "__main__":
    main()
