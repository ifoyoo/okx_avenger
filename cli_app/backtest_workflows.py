from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from loguru import logger

from config.settings import get_settings
from core.backtest import BacktestResult
from core.strategy.plugins import SignalPluginManager

from cli_app.backtest_helpers import (
    BACKTEST_LATEST,
    _build_features_for_backtest,
    _load_backtest_records,
    _market_regime_bucket,
    _plugin_score,
    _print_backtest_summary,
    _run_single_backtest,
    _safe_float,
    _save_backtest_records,
    _scores_to_weights,
)
from cli_app.context import RuntimeBundle
from cli_app.runtime_helpers import DEFAULT_TIMEFRAME, _resolve_entries, _safe_account_snapshot
from cli_app.strategy_config_helpers import (
    _print_strategies,
    _refresh_settings_cache,
    _save_weight_config,
    _strategy_names_from_settings,
)


def _resolve_backtest_entries(
    bundle: RuntimeBundle,
    args: argparse.Namespace,
    *,
    empty_message: str,
) -> List[Dict[str, Any]]:
    account_snapshot = _safe_account_snapshot(bundle.engine)
    entries = _resolve_entries(
        args=args,
        watchlist_manager=bundle.watchlist_manager,
        account_snapshot=account_snapshot,
        default_max_position=bundle.settings.runtime.default_max_position,
    )
    if not entries:
        print(empty_message)
        return []
    return entries


def run_backtest_for_bundle(bundle: RuntimeBundle, args: argparse.Namespace) -> int:
    entries = _resolve_backtest_entries(bundle, args, empty_message="watchlist 为空，无法回测。")
    if not entries:
        return 2

    records: List[Dict[str, Any]] = []
    for item in entries:
        inst_id = item["inst_id"]
        timeframe = item.get("timeframe", DEFAULT_TIMEFRAME)
        max_position = float(item.get("max_position", bundle.settings.runtime.default_max_position))
        try:
            features = _build_features_for_backtest(bundle.okx, inst_id, timeframe, args.limit)
        except Exception as exc:
            logger.warning("回测拉取K线失败 inst={} tf={} err={}", inst_id, timeframe, exc)
            continue
        if features.empty:
            continue
        try:
            result: BacktestResult = _run_single_backtest(
                strategy=bundle.engine.strategy,
                features=features,
                inst_id=inst_id,
                timeframe=timeframe,
                warmup=args.warmup,
                initial_equity=args.initial_equity,
                max_position=max_position if max_position > 0 else bundle.settings.runtime.default_max_position,
                leverage=bundle.engine.leverage,
                fee_rate=args.fee_rate,
                slippage_ratio=args.slippage_ratio,
                spread_ratio=args.spread_ratio,
                max_hold_bars=args.max_hold_bars,
            )
        except Exception as exc:
            logger.warning("回测执行失败 inst={} tf={} err={}", inst_id, timeframe, exc)
            continue
        records.append(result.to_dict())

    if not records:
        print("没有生成任何回测结果。")
        return 2
    path = _save_backtest_records(records)
    print(f"✅ 回测完成，结果已保存: {path}")
    _print_backtest_summary(records)
    return 0


def _filter_backtest_records(records: List[Dict[str, Any]], inst: str | None) -> List[Dict[str, Any]]:
    if not inst:
        return list(records)
    target = str(inst).upper()
    return [
        item
        for item in records
        if str((item.get("summary") or {}).get("inst_id", "")).upper() == target
    ]


def _print_trade_rows(records: List[Dict[str, Any]], max_trades: int) -> None:
    print("\n=== Trades (latest first) ===")
    for item in records:
        summary = item.get("summary") or {}
        trades = list(item.get("trades") or [])
        inst_id = str(summary.get("inst_id", "-"))
        timeframe = str(summary.get("timeframe", "-"))
        print(f"\n[{inst_id} {timeframe}]")
        for trade in list(reversed(trades))[:max_trades]:
            side = str(trade.get("side", "-")).upper()
            qty = _safe_float(trade.get("qty"))
            entry = _safe_float(trade.get("entry_price"))
            exit_px = _safe_float(trade.get("exit_price"))
            net = _safe_float(trade.get("net_pnl"))
            held = int(_safe_float(trade.get("bars_held")))
            print(
                f"- {side:<4} qty={qty:.6f} entry={entry:.6f} exit={exit_px:.6f} "
                f"net={net:+.4f} held={held}"
            )


def report_backtest(args: argparse.Namespace) -> int:
    path = Path(args.file) if args.file else BACKTEST_LATEST
    records = _load_backtest_records(path)
    if not records:
        print(f"未找到回测结果: {path}")
        return 2

    filtered_records = _filter_backtest_records(records, getattr(args, "inst", None))
    if not filtered_records:
        print("没有匹配到指定标的的回测结果。")
        return 2

    _print_backtest_summary(filtered_records)
    if args.show_trades:
        _print_trade_rows(filtered_records, max(1, int(args.max_trades)))
    return 0


def _build_tune_weights(score_buckets: Dict[str, List[float]]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for name, values in score_buckets.items():
        if values:
            scores[name] = sum(values) / len(values)
    return _scores_to_weights(scores)


def _print_tune_report(
    *,
    args: argparse.Namespace,
    scores: Dict[str, float],
    weights: Dict[str, float],
    stats_rows: Dict[str, List[Tuple[int, float, float]]],
    regime_score_buckets: Dict[str, Dict[str, List[float]]],
    scanned_instruments: int,
) -> None:
    print("=== Backtest Tune ===")
    print(f"instruments={scanned_instruments} lookback_bars={args.limit}")
    print(f"{'plugin':<24} {'samples':<8} {'trades':<8} {'win_rate':<9} {'net_pnl':<12} {'score':<8} {'weight':<7}")
    print("-" * 88)
    for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        weight = weights.get(name, 1.0)
        rows = stats_rows.get(name) or []
        samples = len(rows)
        avg_trades = sum(item[0] for item in rows) / samples if samples else 0.0
        avg_win_rate = sum(item[1] for item in rows) / samples if samples else 0.0
        avg_net = sum(item[2] for item in rows) / samples if samples else 0.0
        print(
            f"{name:<24} {samples:<8d} {avg_trades:<8.1f} {avg_win_rate:>6.1f}%  {avg_net:>+10.2f}  {score:>+7.4f}  {weight:>5.2f}"
        )

    print("\n=== Regime Buckets ===")
    for regime, per_plugin in sorted(regime_score_buckets.items(), key=lambda item: item[0]):
        print(f"[{regime}]")
        regime_rows: List[Tuple[str, float]] = []
        for name, values in per_plugin.items():
            if values:
                regime_rows.append((name, sum(values) / len(values)))
        if not regime_rows:
            print("- (no data)")
            continue
        for name, avg_score in sorted(regime_rows, key=lambda item: item[1], reverse=True):
            print(f"- {name:<22} avg_score={avg_score:+.4f}")


def _apply_tune_weights(weights: Dict[str, float], names: List[str]) -> None:
    value = _save_weight_config(weights, names)
    _refresh_settings_cache()
    print(f"\n✅ 已应用推荐权重: STRATEGY_SIGNAL_WEIGHTS={value}")
    _print_strategies(get_settings())


def tune_backtest_for_bundle(bundle: RuntimeBundle, args: argparse.Namespace) -> int:
    entries = _resolve_backtest_entries(bundle, args, empty_message="watchlist 为空，无法调参。")
    if not entries:
        return 2

    names = _strategy_names_from_settings(bundle.settings)
    score_buckets: Dict[str, List[float]] = {name: [] for name in names}
    stats_rows: Dict[str, List[Tuple[int, float, float]]] = {name: [] for name in names}
    regime_score_buckets: Dict[str, Dict[str, List[float]]] = {}
    scanned_instruments = 0

    original_manager = bundle.engine.strategy.signal_generator.plugin_manager
    try:
        for target in entries:
            inst_id = target["inst_id"]
            timeframe = target.get("timeframe", DEFAULT_TIMEFRAME)
            max_position = float(target.get("max_position", bundle.settings.runtime.default_max_position))
            try:
                features = _build_features_for_backtest(bundle.okx, inst_id, timeframe, args.limit)
            except Exception as exc:
                logger.warning("调参拉取K线失败 inst={} tf={} err={}", inst_id, timeframe, exc)
                continue
            if features.empty:
                continue

            scanned_instruments += 1
            regime = _market_regime_bucket(features)
            regime_score_buckets.setdefault(regime, {name: [] for name in names})

            for name in names:
                bundle.engine.strategy.signal_generator.plugin_manager = SignalPluginManager(
                    enabled_raw=name,
                    weights_raw="",
                )
                result = _run_single_backtest(
                    strategy=bundle.engine.strategy,
                    features=features,
                    inst_id=inst_id,
                    timeframe=timeframe,
                    warmup=args.warmup,
                    initial_equity=args.initial_equity,
                    max_position=max_position if max_position > 0 else bundle.settings.runtime.default_max_position,
                    leverage=bundle.engine.leverage,
                    fee_rate=args.fee_rate,
                    slippage_ratio=args.slippage_ratio,
                    spread_ratio=args.spread_ratio,
                    max_hold_bars=args.max_hold_bars,
                )
                summary = result.summary
                score = _plugin_score(result.to_dict()["summary"], args.initial_equity)
                score_buckets[name].append(score)
                stats_rows[name].append((summary.total_trades, summary.win_rate * 100, summary.net_pnl))
                regime_score_buckets[regime][name].append(score)
    finally:
        bundle.engine.strategy.signal_generator.plugin_manager = original_manager

    if scanned_instruments <= 0:
        print("没有可用K线数据，无法调参。")
        return 2

    scores = {name: sum(values) / len(values) for name, values in score_buckets.items() if values}
    weights = _build_tune_weights(score_buckets)
    _print_tune_report(
        args=args,
        scores=scores,
        weights=weights,
        stats_rows=stats_rows,
        regime_score_buckets=regime_score_buckets,
        scanned_instruments=scanned_instruments,
    )

    if args.apply:
        _apply_tune_weights(weights, names)
    else:
        print("\nℹ️ 仅预览，未写入 .env。加 --apply 可应用。")
    return 0
