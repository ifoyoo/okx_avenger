from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

from loguru import logger

from config.settings import get_settings
from core.backtest import BacktestResult
from core.strategy.plugins import SignalPluginManager

from cli_app.context import build_runtime
from cli_app.helpers import (
    BACKTEST_LATEST,
    DEFAULT_TIMEFRAME,
    _build_features_for_backtest,
    _load_backtest_records,
    _market_regime_bucket,
    _plugin_score,
    _print_backtest_summary,
    _resolve_entries,
    _run_single_backtest,
    _safe_account_snapshot,
    _safe_float,
    _save_backtest_records,
    _scores_to_weights,
)
from cli_app.commands.strategies import (
    _print_strategies,
    _refresh_settings_cache,
    _save_weight_config,
    _strategy_names_from_settings,
)


def cmd_backtest_run(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        account_snapshot = _safe_account_snapshot(bundle.engine)
        entries = _resolve_entries(
            args=args,
            watchlist_manager=bundle.watchlist_manager,
            account_snapshot=account_snapshot,
            default_max_position=bundle.settings.runtime.default_max_position,
        )
        if not entries:
            print("watchlist 为空，无法回测。")
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
    finally:
        bundle.close()


def cmd_backtest_report(args: argparse.Namespace) -> int:
    path = Path(args.file) if args.file else BACKTEST_LATEST
    records = _load_backtest_records(path)
    if not records:
        print(f"未找到回测结果: {path}")
        return 2
    if args.inst:
        records = [
            item for item in records
            if str((item.get("summary") or {}).get("inst_id", "")).upper() == str(args.inst).upper()
        ]
    if not records:
        print("没有匹配到指定标的的回测结果。")
        return 2
    _print_backtest_summary(records)
    if args.show_trades:
        print("\n=== Trades (latest first) ===")
        max_rows = max(1, int(args.max_trades))
        for item in records:
            summary = item.get("summary") or {}
            trades = list(item.get("trades") or [])
            inst_id = str(summary.get("inst_id", "-"))
            timeframe = str(summary.get("timeframe", "-"))
            print(f"\n[{inst_id} {timeframe}]")
            for trade in list(reversed(trades))[:max_rows]:
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
    return 0


def cmd_backtest_tune(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        account_snapshot = _safe_account_snapshot(bundle.engine)
        entries = _resolve_entries(
            args=args,
            watchlist_manager=bundle.watchlist_manager,
            account_snapshot=account_snapshot,
            default_max_position=bundle.settings.runtime.default_max_position,
        )
        if not entries:
            print("watchlist 为空，无法调参。")
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
                    manager = SignalPluginManager(enabled_raw=name, weights_raw="")
                    bundle.engine.strategy.signal_generator.plugin_manager = manager
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
                    stats_rows[name].append(
                        (summary.total_trades, summary.win_rate * 100, summary.net_pnl)
                    )
                    regime_score_buckets[regime][name].append(score)
        finally:
            bundle.engine.strategy.signal_generator.plugin_manager = original_manager

        if scanned_instruments <= 0:
            print("没有可用K线数据，无法调参。")
            return 2

        scores: Dict[str, float] = {}
        for name, values in score_buckets.items():
            if not values:
                continue
            scores[name] = sum(values) / len(values)
        weights = _scores_to_weights(scores)
        print("=== Backtest Tune ===")
        print(f"instruments={scanned_instruments} lookback_bars={args.limit}")
        print(f"{'plugin':<24} {'samples':<8} {'trades':<8} {'win_rate':<9} {'net_pnl':<12} {'score':<8} {'weight':<7}")
        print("-" * 88)
        for name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
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
                if not values:
                    continue
                regime_rows.append((name, sum(values) / len(values)))
            if not regime_rows:
                print("- (no data)")
                continue
            for name, avg_score in sorted(regime_rows, key=lambda item: item[1], reverse=True):
                print(f"- {name:<22} avg_score={avg_score:+.4f}")

        if args.apply:
            value = _save_weight_config(weights, names)
            _refresh_settings_cache()
            print(f"\n✅ 已应用推荐权重: STRATEGY_SIGNAL_WEIGHTS={value}")
            _print_strategies(get_settings())
        else:
            print("\nℹ️ 仅预览，未写入 .env。加 --apply 可应用。")
        return 0
    finally:
        bundle.close()


def register_backtest_commands(subparsers) -> None:
    p_backtest = subparsers.add_parser("backtest", help="运行或查看策略回测")
    p_backtest_sub = p_backtest.add_subparsers(dest="backtest_action", required=True)

    p_backtest_run = p_backtest_sub.add_parser("run", help="执行回测并保存结果")
    p_backtest_run.add_argument("--inst", help="指定单个交易对，例如 BTC-USDT-SWAP")
    p_backtest_run.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="K线周期，默认 5m")
    p_backtest_run.add_argument(
        "--higher-timeframes",
        default="1H",
        help="保留参数（与 once/run 对齐），回测暂不使用",
    )
    p_backtest_run.add_argument("--max-position", type=float, default=0.0, help="单标的最大下单量")
    p_backtest_run.add_argument("--limit", type=int, default=600, help="回测K线数量，默认 600")
    p_backtest_run.add_argument("--warmup", type=int, default=120, help="预热K线数量，默认 120")
    p_backtest_run.add_argument("--initial-equity", type=float, default=10_000.0, help="初始资金，默认 10000")
    p_backtest_run.add_argument("--fee-rate", type=float, default=0.0005, help="单边手续费率，默认 0.0005")
    p_backtest_run.add_argument("--slippage-ratio", type=float, default=0.0002, help="滑点比例，默认 0.0002")
    p_backtest_run.add_argument("--spread-ratio", type=float, default=0.0001, help="点差比例，默认 0.0001")
    p_backtest_run.add_argument("--max-hold-bars", type=int, default=48, help="最长持仓K线数，默认 48")
    p_backtest_run.set_defaults(func=cmd_backtest_run)

    p_backtest_report = p_backtest_sub.add_parser("report", help="查看回测报告")
    p_backtest_report.add_argument("--file", help="指定报告文件，默认 data/backtests/latest.json")
    p_backtest_report.add_argument("--inst", help="仅查看指定交易对")
    p_backtest_report.add_argument("--show-trades", action="store_true", help="展示成交明细")
    p_backtest_report.add_argument("--max-trades", type=int, default=10, help="每个标的最多展示成交条数")
    p_backtest_report.set_defaults(func=cmd_backtest_report)

    p_backtest_tune = p_backtest_sub.add_parser("tune", help="基于回测推荐策略权重")
    p_backtest_tune.add_argument("--inst", help="指定单个交易对，例如 BTC-USDT-SWAP")
    p_backtest_tune.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="K线周期，默认 5m")
    p_backtest_tune.add_argument(
        "--higher-timeframes",
        default="1H",
        help="保留参数（与 once/run 对齐），调参暂不使用",
    )
    p_backtest_tune.add_argument("--max-position", type=float, default=0.0, help="单标的最大下单量")
    p_backtest_tune.add_argument("--limit", type=int, default=800, help="回测K线数量，默认 800")
    p_backtest_tune.add_argument("--warmup", type=int, default=120, help="预热K线数量，默认 120")
    p_backtest_tune.add_argument("--initial-equity", type=float, default=10_000.0, help="初始资金，默认 10000")
    p_backtest_tune.add_argument("--fee-rate", type=float, default=0.0005, help="单边手续费率，默认 0.0005")
    p_backtest_tune.add_argument("--slippage-ratio", type=float, default=0.0002, help="滑点比例，默认 0.0002")
    p_backtest_tune.add_argument("--spread-ratio", type=float, default=0.0001, help="点差比例，默认 0.0001")
    p_backtest_tune.add_argument("--max-hold-bars", type=int, default=48, help="最长持仓K线数，默认 48")
    p_backtest_tune.add_argument("--apply", action="store_true", help="把推荐权重写入 .env")
    p_backtest_tune.set_defaults(func=cmd_backtest_tune)
