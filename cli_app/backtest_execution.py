from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from loguru import logger

from core.backtest import BacktestResult
from core.strategy.plugins import SignalPluginManager

from cli_app.backtest_helpers import (
    _build_features_for_backtest,
    _build_higher_timeframe_features_for_backtest,
    _market_regime_bucket,
    _plugin_score,
    _run_single_backtest,
    _scores_to_weights,
)
from cli_app.context import RuntimeBundle
from cli_app.runtime_helpers import DEFAULT_HIGHER_TIMEFRAMES, DEFAULT_TIMEFRAME


@dataclass
class BacktestTuningSnapshot:
    score_buckets: Dict[str, List[float]]
    scores: Dict[str, float]
    weights: Dict[str, float]
    stats_rows: Dict[str, List[Tuple[int, float, float]]]
    regime_score_buckets: Dict[str, Dict[str, List[float]]]
    scanned_instruments: int


def _effective_max_position(bundle: RuntimeBundle, raw_value: Any) -> float:
    max_position = float(raw_value or 0.0)
    if max_position > 0:
        return max_position
    return float(bundle.settings.runtime.default_max_position)


def _run_backtest_entry(
    *,
    bundle: RuntimeBundle,
    args: argparse.Namespace,
    inst_id: str,
    timeframe: str,
    features: Any,
    higher_timeframe_features: Any,
    max_position: Any,
):
    return _run_single_backtest(
        strategy=bundle.engine.strategy,
        features=features,
        higher_timeframe_features=higher_timeframe_features,
        inst_id=inst_id,
        timeframe=timeframe,
        warmup=args.warmup,
        initial_equity=args.initial_equity,
        max_position=_effective_max_position(bundle, max_position),
        leverage=bundle.engine.leverage,
        fee_rate=args.fee_rate,
        slippage_ratio=args.slippage_ratio,
        spread_ratio=args.spread_ratio,
        max_hold_bars=args.max_hold_bars,
    )


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
        higher_timeframes = tuple(item.get("higher_timeframes") or DEFAULT_HIGHER_TIMEFRAMES)
        max_position = item.get("max_position")
        try:
            features = _build_features_for_backtest(bundle.okx, inst_id, timeframe, args.limit)
            higher_features = _build_higher_timeframe_features_for_backtest(
                bundle.okx,
                inst_id,
                higher_timeframes,
                args.limit,
            )
        except Exception as exc:
            logger.warning("回测拉取K线失败 inst={} tf={} err={}", inst_id, timeframe, exc)
            continue
        if features.empty:
            continue
        try:
            result: BacktestResult = _run_backtest_entry(
                bundle=bundle,
                args=args,
                inst_id=inst_id,
                timeframe=timeframe,
                features=features,
                higher_timeframe_features=higher_features,
                max_position=max_position,
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
            higher_timeframes = tuple(target.get("higher_timeframes") or DEFAULT_HIGHER_TIMEFRAMES)
            max_position = target.get("max_position")
            try:
                features = _build_features_for_backtest(bundle.okx, inst_id, timeframe, args.limit)
                higher_features = _build_higher_timeframe_features_for_backtest(
                    bundle.okx,
                    inst_id,
                    higher_timeframes,
                    args.limit,
                )
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
                result = _run_backtest_entry(
                    bundle=bundle,
                    args=args,
                    inst_id=inst_id,
                    timeframe=timeframe,
                    features=features,
                    higher_timeframe_features=higher_features,
                    max_position=max_position,
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
