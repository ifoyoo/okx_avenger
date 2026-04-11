from __future__ import annotations

import argparse
from typing import Optional

from loguru import logger

from cli_app.context import RuntimeBundle
from cli_app.runtime_helpers import (
    DEFAULT_HIGHER_TIMEFRAMES,
    DEFAULT_TIMEFRAME,
    _fmt_action,
    _fmt_plan,
    _resolve_entries,
    _safe_account_snapshot,
)
from core.engine.execution import ExecutionPlan
from core.models import TradeSignal
from core.strategy.plugins import format_plugin_snapshot


def run_runtime_cycle(bundle: RuntimeBundle, args: argparse.Namespace) -> int:
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


def log_strategy_snapshot(bundle: RuntimeBundle) -> None:
    try:
        manager = bundle.engine.strategy.signal_generator.plugin_manager
    except Exception:
        return
    logger.info("策略插件: {}", format_plugin_snapshot(manager))
