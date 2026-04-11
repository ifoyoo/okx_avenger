from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from loguru import logger

from core.backtest import BacktestResult
from core.strategy.plugins import SignalPluginManager

from cli_app.backtest_helpers import (
    _build_features_for_backtest,
    _market_regime_bucket,
    _plugin_score,
    _run_single_backtest,
    _scores_to_weights,
)
from cli_app.context import RuntimeBundle
from cli_app.runtime_helpers import DEFAULT_TIMEFRAME


@dataclass
class BacktestTuningSnapshot:
    score_buckets: Dict[str, List[float]]
    scores: Dict[str, float]
    weights: Dict[str, float]
    stats_rows: Dict[str, List[Tuple[int, float, float]]]
    regime_score_buckets: Dict[str, Dict[str, List[float]]]
    scanned_instruments: int


def collect_backtest_records(
    *,
    bundle: RuntimeBundle,
    args: argparse.Namespace,
    entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
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
    return records


def collect_tuning_snapshot(
    *,
    bundle: RuntimeBundle,
    args: argparse.Namespace,
    entries: List[Dict[str, Any]],
    names: List[str],
) -> BacktestTuningSnapshot:
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

    scores = {name: sum(values) / len(values) for name, values in score_buckets.items() if values}
    return BacktestTuningSnapshot(
        score_buckets=score_buckets,
        scores=scores,
        weights=_scores_to_weights(scores),
        stats_rows=stats_rows,
        regime_score_buckets=regime_score_buckets,
        scanned_instruments=scanned_instruments,
    )
