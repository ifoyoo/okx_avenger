from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from cli_app.context import RuntimeBundle, build_runtime
from cli_app.runtime_helpers import (
    DEFAULT_HIGHER_TIMEFRAMES,
    DEFAULT_TIMEFRAME,
    _fmt_action,
    _fmt_plan,
    _read_runtime_heartbeat,
    _resolve_entries,
    _safe_account_snapshot,
    _write_runtime_heartbeat,
)
from cli_app.runtime_status_helpers import (
    _format_account_lines,
    _format_heartbeat_lines,
    _format_position_lines,
    _format_watchlist_lines,
)
from core.engine.execution import ExecutionPlan
from core.models import TradeSignal
from core.strategy.plugins import format_plugin_snapshot


def _run_cycle(bundle: RuntimeBundle, args: argparse.Namespace) -> int:
    account_snapshot = _safe_account_snapshot(bundle.engine)
    perf_stats = bundle.perf_tracker.get_snapshot()
    daily_stats = bundle.perf_tracker.get_snapshot_for_days(1)
    entries = _resolve_entries(
        args=args,
        watchlist_manager=bundle.watchlist_manager,
        account_snapshot=account_snapshot,
        default_max_position=bundle.settings.runtime.default_max_position,
    )
    if not entries:
        logger.warning("watchlist 为空，本轮跳过。")
        return 0

    logger.info("开始执行，本轮 {} 个标的（dry_run={}）", len(entries), bool(args.dry_run))
    success = 0
    for item in entries:
        inst_id = item["inst_id"]
        timeframe = item.get("timeframe", DEFAULT_TIMEFRAME)
        higher_timeframes = tuple(item.get("higher_timeframes", DEFAULT_HIGHER_TIMEFRAMES))
        max_position = float(item.get("max_position", bundle.settings.runtime.default_max_position))
        protection_overrides = item.get("protection")
        if protection_overrides is not None and not isinstance(protection_overrides, dict):
            protection_overrides = None
        try:
            result = bundle.engine.run_once(
                inst_id=inst_id,
                timeframe=timeframe,
                limit=args.limit,
                dry_run=bool(args.dry_run),
                max_position=max_position,
                higher_timeframes=higher_timeframes,
                market_intel_query=item.get("news_query"),
                market_intel_coin_id=item.get("news_coin_id"),
                market_intel_aliases=item.get("news_aliases"),
                account_snapshot=account_snapshot,
                protection_overrides=protection_overrides,
                perf_stats=perf_stats,
                daily_stats=daily_stats,
            )
        except Exception as exc:
            logger.error("[{} {}] 执行失败: {}", inst_id, timeframe, exc)
            continue

        signal: TradeSignal = result["signal"]
        plan: Optional[ExecutionPlan] = (result.get("execution") or {}).get("plan")
        brain = result.get("analysis_brain")
        intel = result.get("market_intel")
        brain_text = ""
        if brain:
            brain_text = (
                f" | brain={str(brain.get('action', '-')).upper()} "
                f"{float(brain.get('confidence', 0.0) or 0.0):.2f}"
            )
        intel_text = ""
        if intel:
            intel_text = f" | intel={float(intel.get('sentiment_score', 0.0) or 0.0):+.2f}"
        logger.info(
            "[{} {}] {} | {}{}{}",
            inst_id,
            timeframe,
            _fmt_action(signal),
            _fmt_plan(plan),
            brain_text,
            intel_text,
        )
        success += 1
    logger.info("本轮结束：{}/{} 成功完成", success, len(entries))
    return 0 if success > 0 else 2


def _log_strategy_snapshot(bundle: RuntimeBundle) -> None:
    try:
        manager = bundle.engine.strategy.signal_generator.plugin_manager
    except Exception:
        return
    logger.info("策略插件: {}", format_plugin_snapshot(manager))


def cmd_once(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
    try:
        _write_runtime_heartbeat(path=heartbeat_path, status="running", cycle=1)
        _log_strategy_snapshot(bundle)
        exit_code = _run_cycle(bundle, args)
        _write_runtime_heartbeat(path=heartbeat_path, status="idle", cycle=1, exit_code=exit_code)
        return exit_code
    except Exception as exc:
        _write_runtime_heartbeat(path=heartbeat_path, status="error", cycle=1, exit_code=2, detail=str(exc))
        raise
    finally:
        bundle.close()


def cmd_run(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
    interval = max(1, int(args.interval_minutes or bundle.settings.runtime.run_interval_minutes))
    logger.info("进入循环模式，间隔 {} 分钟（Ctrl+C 退出）", interval)
    _log_strategy_snapshot(bundle)
    cycle = 0
    try:
        while True:
            cycle += 1
            started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info("===== 新一轮扫描开始 {} =====", started)
            _write_runtime_heartbeat(path=heartbeat_path, status="running", cycle=cycle)
            exit_code = _run_cycle(bundle, args)
            state = "idle" if exit_code == 0 else "error"
            _write_runtime_heartbeat(path=heartbeat_path, status=state, cycle=cycle, exit_code=exit_code)
            logger.info("===== 本轮结束，休眠 {} 分钟 =====", interval)
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        _write_runtime_heartbeat(path=heartbeat_path, status="stopped", cycle=cycle, exit_code=0)
        logger.info("收到中断信号，退出。")
        return 0
    except Exception as exc:
        _write_runtime_heartbeat(path=heartbeat_path, status="error", cycle=cycle, exit_code=2, detail=str(exc))
        raise
    finally:
        bundle.close()


def cmd_status(_: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        account_snapshot = _safe_account_snapshot(bundle.engine)
        print("=== Account ===")
        for row in _format_account_lines(account_snapshot):
            print(row)

        print("\n=== Watchlist ===")
        entries = bundle.watchlist_manager.get_watchlist(account_snapshot)
        for row in _format_watchlist_lines(entries):
            print(row)

        print("\n=== Position ===")
        try:
            positions = bundle.okx.get_positions(inst_type="SWAP").get("data") or []
        except Exception as exc:
            print(f"query failed: {exc}")
            return 1
        if not positions:
            print("(no positions)")
        else:
            for row in _format_position_lines(positions):
                print(row)
        heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
        heartbeat = _read_runtime_heartbeat(heartbeat_path)
        print("\n=== Runtime Heartbeat ===")
        for row in _format_heartbeat_lines(heartbeat_path, heartbeat):
            print(row)
        return 0
    finally:
        bundle.close()
