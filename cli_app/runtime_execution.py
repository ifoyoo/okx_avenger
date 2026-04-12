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
from core.models import SignalAction, TradeSignal
from core.strategy.plugins import format_plugin_snapshot
from core.utils import NotificationEvent


def _publish_runtime_error(bundle: RuntimeBundle, *, inst_id: str, timeframe: str, detail: str) -> None:
    notifier = getattr(bundle, "notifier", None)
    if notifier is None:
        return
    notifier.publish(
        NotificationEvent(
            kind="runtime_error",
            inst_id=inst_id,
            timeframe=timeframe,
            message=f"[{inst_id} {timeframe}] runtime_error: {detail}",
        )
    )


def _publish_runtime_result(
    bundle: RuntimeBundle,
    *,
    inst_id: str,
    timeframe: str,
    dry_run: bool,
    signal: TradeSignal,
    plan: Optional[ExecutionPlan],
    execution_report: Optional[object],
    order: Optional[dict],
) -> None:
    notifier = getattr(bundle, "notifier", None)
    if notifier is None:
        return
    if signal.action == SignalAction.HOLD:
        return
    if plan and plan.blocked and plan.block_reason:
        notifier.publish(
            NotificationEvent(
                kind="trade_blocked",
                inst_id=inst_id,
                timeframe=timeframe,
                message=(
                    f"[{inst_id} {timeframe}] {signal.action.value.upper()} blocked "
                    f"conf={signal.confidence:.2f} reason={plan.block_reason}"
                ),
            )
        )
        return
    if dry_run:
        return
    success = bool(getattr(execution_report, "success", False))
    if success:
        notifier.publish(
            NotificationEvent(
                kind="order_submitted",
                inst_id=inst_id,
                timeframe=timeframe,
                message=(
                    f"[{inst_id} {timeframe}] order_submitted "
                    f"{signal.action.value.upper()} conf={signal.confidence:.2f} size={signal.size:.6f}"
                ),
            )
        )
        return
    error_text = str(getattr(execution_report, "error", "") or "")
    code_text = str(getattr(execution_report, "code", "") or "")
    if isinstance(order, dict) and not error_text:
        error_info = order.get("error") if isinstance(order.get("error"), dict) else {}
        if error_info:
            error_text = str(error_info.get("message") or "")
            code_text = code_text or str(error_info.get("code") or "")
    if error_text or code_text:
        notifier.publish(
            NotificationEvent(
                kind="order_failed",
                inst_id=inst_id,
                timeframe=timeframe,
                message=(
                    f"[{inst_id} {timeframe}] order_failed {signal.action.value.upper()} "
                    f"code={code_text or '-'} msg={error_text or '-'}"
                ),
            )
        )


def _is_failed_execution_result(
    *,
    signal: TradeSignal,
    plan: Optional[ExecutionPlan],
    execution_report: Optional[object],
    order: Optional[dict],
) -> bool:
    if signal.action == SignalAction.HOLD:
        return False
    if plan and plan.blocked:
        return False
    order_error = bool(isinstance(order, dict) and isinstance(order.get("error"), dict))
    if execution_report is None:
        return order_error
    return not bool(getattr(execution_report, "success", False)) or order_error


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
    completed = 0
    blocked = 0
    hold = 0
    failed = 0
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
            _publish_runtime_error(bundle, inst_id=inst_id, timeframe=timeframe, detail=str(exc))
            failed += 1
            continue

        signal: TradeSignal = result["signal"]
        plan: Optional[ExecutionPlan] = (result.get("execution") or {}).get("plan")
        report = (result.get("execution") or {}).get("report")
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
        _publish_runtime_result(
            bundle,
            inst_id=inst_id,
            timeframe=timeframe,
            dry_run=bool(args.dry_run),
            signal=signal,
            plan=plan,
            execution_report=report,
            order=result.get("order"),
        )
        if signal.action == SignalAction.HOLD:
            hold += 1
        elif plan and plan.blocked:
            blocked += 1
        elif _is_failed_execution_result(
            signal=signal,
            plan=plan,
            execution_report=report,
            order=result.get("order"),
        ):
            failed += 1
        else:
            completed += 1
    logger.info(
        "本轮结束：总计 {}，完成 {}，阻断 {}，观望 {}，失败 {}",
        len(entries),
        completed,
        blocked,
        hold,
        failed,
    )
    if failed == 0:
        return 0
    return 1 if (completed + blocked + hold) > 0 else 2


def log_strategy_snapshot(bundle: RuntimeBundle) -> None:
    try:
        manager = bundle.engine.strategy.signal_generator.plugin_manager
    except Exception:
        return
    logger.info("策略插件: {}", format_plugin_snapshot(manager))
