from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
import pandas as pd

from core.backtest import BacktestResult, run_backtest_from_features
from core.client import OKXClient
from core.data.features import candles_to_dataframe
from core.data.watchlist_loader import WatchlistManager
from core.engine.execution import ExecutionPlan
from core.engine.trading import TradingEngine
from core.models import TradeSignal
from core.strategy.core import Strategy

DEFAULT_LIMIT = 150
DEFAULT_TIMEFRAME = "5m"
DEFAULT_HIGHER_TIMEFRAMES: Tuple[str, ...] = ("1H",)
ENV_FILE = Path(".env")
BACKTEST_DIR = Path("data/backtests")
BACKTEST_LATEST = BACKTEST_DIR / "latest.json"


def _parse_timeframes(raw: str) -> Tuple[str, ...]:
    parts = [part.strip() for part in (raw or "").split(",") if part.strip()]
    return tuple(parts)


def _fmt_action(signal: TradeSignal) -> str:
    return f"{signal.action.value.upper():<4} conf={signal.confidence:.2f} size={signal.size:.6f}"


def _fmt_plan(plan: Optional[ExecutionPlan]) -> str:
    if not plan:
        return "no-plan"
    if plan.blocked:
        return f"BLOCKED({plan.block_reason or 'unknown'})"
    return f"{plan.order_type.upper()} slip={plan.est_slippage:.2%}"


def _safe_account_snapshot(engine: TradingEngine) -> Dict[str, float]:
    try:
        balance = engine.okx.get_account_balance()
        return engine.build_account_snapshot(balance)
    except Exception as exc:
        logger.warning("获取账户快照失败: {}", exc)
        return {}


def _resolve_entries(
    *,
    args: argparse.Namespace,
    watchlist_manager: WatchlistManager,
    account_snapshot: Dict[str, float],
    default_max_position: float,
) -> List[Dict[str, Any]]:
    if args.inst:
        higher = _parse_timeframes(args.higher_timeframes or "")
        return [
            {
                "inst_id": args.inst,
                "timeframe": args.timeframe or DEFAULT_TIMEFRAME,
                "higher_timeframes": higher or DEFAULT_HIGHER_TIMEFRAMES,
                "max_position": args.max_position or default_max_position,
            }
        ]
    return watchlist_manager.get_watchlist(account_snapshot)


def _write_runtime_heartbeat(
    *,
    path: Path,
    status: str,
    cycle: int = 0,
    exit_code: int = 0,
    detail: str = "",
) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "cycle": int(cycle),
        "exit_code": int(exit_code),
        "detail": str(detail or ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _read_runtime_heartbeat(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _serialize_backtest_record(record: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(record.get("summary") or {})
    if summary.get("profit_factor") == float("inf"):
        summary["profit_factor"] = "inf"
    output = dict(record)
    output["summary"] = summary
    return output


def _save_backtest_records(records: List[Dict[str, Any]]) -> Path:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "records": [_serialize_backtest_record(item) for item in records],
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKTEST_DIR / f"backtest-{stamp}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    with BACKTEST_LATEST.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def _load_backtest_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    records = payload.get("records") or []
    if not isinstance(records, list):
        return []
    return records


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


def _human_ratio(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{(numerator / denominator) * 100:.1f}%"
