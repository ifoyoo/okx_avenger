from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from core.backtest import BacktestResult, run_backtest_from_features
from core.client import OKXClient
from core.data.features import candles_to_dataframe
from core.strategy.core import Strategy


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _print_backtest_summary(records: List[Dict[str, Any]]) -> None:
    if not records:
        print("暂无回测结果。")
        return
    print("=== Backtest Summary ===")
    print(f"{'inst':<18} {'tf':<5} {'trades':<8} {'win_rate':<9} {'net_pnl':<12} {'max_dd':<8}")
    print("-" * 70)
    for item in records:
        s = item.get("summary") or {}
        inst = str(s.get("inst_id", "-"))
        tf = str(s.get("timeframe", "-"))
        trades = int(_safe_float(s.get("total_trades")))
        win_rate = _safe_float(s.get("win_rate")) * 100
        net_pnl = _safe_float(s.get("net_pnl"))
        max_dd = _safe_float(s.get("max_drawdown")) * 100
        print(f"{inst:<18} {tf:<5} {trades:<8d} {win_rate:>6.1f}%  {net_pnl:>+10.2f}  {max_dd:>6.1f}%")


def _build_features_for_backtest(okx: OKXClient, inst_id: str, timeframe: str, limit: int) -> pd.DataFrame:
    resp = okx.get_candles(inst_id=inst_id, bar=timeframe, limit=limit)
    raw = resp.get("data") or []
    return candles_to_dataframe(raw).tail(limit)


def _run_single_backtest(
    *,
    strategy: Strategy,
    features: pd.DataFrame,
    inst_id: str,
    timeframe: str,
    warmup: int,
    initial_equity: float,
    max_position: float,
    leverage: float,
    fee_rate: float,
    slippage_ratio: float,
    spread_ratio: float,
    max_hold_bars: int,
) -> BacktestResult:
    return run_backtest_from_features(
        strategy=strategy,
        features=features,
        inst_id=inst_id,
        timeframe=timeframe,
        warmup=warmup,
        initial_equity=initial_equity,
        max_position=max_position,
        leverage=leverage,
        fee_rate=fee_rate,
        slippage_ratio=slippage_ratio,
        spread_ratio=spread_ratio,
        max_hold_bars=max_hold_bars,
    )


def _plugin_score(summary: Dict[str, Any], initial_equity: float) -> float:
    net_pnl = _safe_float(summary.get("net_pnl"))
    win_rate = _safe_float(summary.get("win_rate"))
    max_dd = _safe_float(summary.get("max_drawdown"))
    trades = _safe_float(summary.get("total_trades"))
    pnl_ratio = (net_pnl / initial_equity) if initial_equity > 0 else 0.0
    trade_bonus = min(0.1, trades / 300.0)
    return pnl_ratio + (win_rate - 0.5) - max_dd * 0.6 + trade_bonus


def _market_regime_bucket(features: pd.DataFrame) -> str:
    if features is None or features.empty:
        return "unknown"
    node = features.tail(30)
    close = node.get("close")
    atr = node.get("atr")
    if close is None or atr is None:
        return "unknown"
    close_mean = float(close.mean() or 0.0)
    atr_mean = float(atr.mean() or 0.0)
    if close_mean <= 0:
        return "unknown"
    ratio = atr_mean / close_mean
    if ratio < 0.006:
        return "low_vol"
    if ratio > 0.02:
        return "high_vol"
    return "mid_vol"


def _scores_to_weights(scores: Dict[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo = min(values)
    hi = max(values)
    if abs(hi - lo) < 1e-12:
        return {name: 1.0 for name in scores}
    weights: Dict[str, float] = {}
    for name, value in scores.items():
        rank = (value - lo) / (hi - lo)
        weights[name] = round(0.7 + rank * 0.8, 2)
    return weights
