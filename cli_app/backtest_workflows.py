from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from config.settings import get_settings

from cli_app.backtest_execution import collect_backtest_records, collect_tuning_snapshot
from cli_app.backtest_helpers import (
    BACKTEST_LATEST,
    _load_backtest_records,
    _print_backtest_summary,
    _save_backtest_records,
)
from cli_app.backtest_reporting import format_trade_lines, format_tune_lines
from cli_app.context import RuntimeBundle
from cli_app.runtime_helpers import _resolve_entries, _safe_account_snapshot
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

    records = collect_backtest_records(bundle=bundle, args=args, entries=entries)

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
    for line in format_trade_lines(records, max_trades):
        print(line)


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


def _print_tune_report(
    *,
    args: argparse.Namespace,
    snapshot,
) -> None:
    for line in format_tune_lines(
        lookback_bars=int(args.limit),
        scanned_instruments=snapshot.scanned_instruments,
        scores=snapshot.scores,
        weights=snapshot.weights,
        stats_rows=snapshot.stats_rows,
        regime_score_buckets=snapshot.regime_score_buckets,
    ):
        print(line)


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
    snapshot = collect_tuning_snapshot(bundle=bundle, args=args, entries=entries, names=names)
    if snapshot.scanned_instruments <= 0:
        print("没有可用K线数据，无法调参。")
        return 2

    _print_tune_report(
        args=args,
        snapshot=snapshot,
    )

    if args.apply:
        _apply_tune_weights(snapshot.weights, names)
    else:
        print("\nℹ️ 仅预览，未写入 .env。加 --apply 可应用。")
    return 0
