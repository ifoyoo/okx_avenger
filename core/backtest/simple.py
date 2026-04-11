"""轻量回测器：基于策略信号做顺序回放。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from core.models import SignalAction, StrategyContext
from core.strategy.core import Strategy


@dataclass
class BacktestTrade:
    inst_id: str
    timeframe: str
    side: str
    qty: float
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    bars_held: int
    reason_entry: str
    reason_exit: str
    gross_pnl: float
    fee: float
    net_pnl: float


@dataclass
class BacktestSummary:
    inst_id: str
    timeframe: str
    bars: int
    warmup: int
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    gross_pnl: float
    fee_total: float
    net_pnl: float
    avg_trade_pnl: float
    profit_factor: float
    max_drawdown: float
    initial_equity: float
    final_equity: float


@dataclass
class BacktestResult:
    summary: BacktestSummary
    trades: List[BacktestTrade]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": asdict(self.summary),
            "trades": [asdict(item) for item in self.trades],
            "metadata": self.metadata,
        }


def _safe_ts(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.isoformat()
    return str(value)


def _pnl(side: SignalAction, qty: float, entry: float, exit_px: float) -> float:
    if side == SignalAction.BUY:
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def _execution_price(
    *,
    raw_price: float,
    side: SignalAction,
    is_entry: bool,
    slippage_ratio: float,
    spread_ratio: float,
) -> float:
    if raw_price <= 0:
        return raw_price
    impact = max(0.0, slippage_ratio) + max(0.0, spread_ratio) * 0.5
    if side == SignalAction.BUY:
        return raw_price * (1 + impact if is_entry else 1 - impact)
    if side == SignalAction.SELL:
        return raw_price * (1 - impact if is_entry else 1 + impact)
    return raw_price


def run_backtest_from_features(
    *,
    strategy: Strategy,
    features: pd.DataFrame,
    inst_id: str,
    timeframe: str,
    warmup: int = 120,
    initial_equity: float = 10_000.0,
    max_position: float = 0.002,
    leverage: float = 1.0,
    fee_rate: float = 0.0005,
    slippage_ratio: float = 0.0002,
    spread_ratio: float = 0.0001,
    max_hold_bars: int = 48,
    analysis_text: str = '{"action":"hold","confidence":0.5,"reason":"backtest"}',
) -> BacktestResult:
    if features is None or features.empty:
        raise ValueError("回测数据为空")
    if len(features) < warmup + 2:
        raise ValueError(f"回测数据不足：len={len(features)} warmup={warmup}")

    equity = float(initial_equity)
    equity_curve: List[float] = [equity]
    peak = equity
    max_drawdown = 0.0

    trades: List[BacktestTrade] = []
    position: Optional[Dict[str, Any]] = None

    for i in range(warmup, len(features) - 1):
        hist = features.iloc[: i + 1]
        next_bar = features.iloc[i + 1]
        next_open = float(next_bar.get("open", 0.0) or next_bar.get("close", 0.0) or 0.0)
        if next_open <= 0:
            continue

        context = StrategyContext(
            inst_id=inst_id,
            timeframe=timeframe,
            dry_run=True,
            max_position=max_position,
            leverage=leverage,
            account_equity=equity,
            available_balance=equity,
        )
        signal = strategy.generate_signal(context, hist, analysis_text, None).trade_signal

        if position is None:
            if signal.action in (SignalAction.BUY, SignalAction.SELL) and signal.size > 0:
                entry_exec = _execution_price(
                    raw_price=next_open,
                    side=signal.action,
                    is_entry=True,
                    slippage_ratio=slippage_ratio,
                    spread_ratio=spread_ratio,
                )
                position = {
                    "side": signal.action,
                    "qty": float(signal.size),
                    "entry_price": entry_exec,
                    "entry_idx": i + 1,
                    "entry_ts": _safe_ts(next_bar.get("ts")),
                    "reason_entry": signal.reason.splitlines()[0] if signal.reason else signal.action.value,
                }
            continue

        held = (i + 1) - int(position["entry_idx"])
        close_now = False
        reason_exit = ""

        if signal.action in (SignalAction.BUY, SignalAction.SELL) and signal.action != position["side"] and signal.size > 0:
            close_now = True
            reason_exit = "opposite_signal"
        elif held >= max_hold_bars:
            close_now = True
            reason_exit = "max_hold_bars"

        if not close_now:
            continue

        qty = float(position["qty"])
        entry_price = float(position["entry_price"])
        exit_exec = _execution_price(
            raw_price=next_open,
            side=position["side"],
            is_entry=False,
            slippage_ratio=slippage_ratio,
            spread_ratio=spread_ratio,
        )
        gross = _pnl(position["side"], qty, entry_price, exit_exec)
        fee = (entry_price + exit_exec) * qty * max(0.0, fee_rate)
        net = gross - fee
        equity += net

        trades.append(
            BacktestTrade(
                inst_id=inst_id,
                timeframe=timeframe,
                side=position["side"].value,
                qty=qty,
                entry_ts=str(position["entry_ts"]),
                exit_ts=_safe_ts(next_bar.get("ts")),
                entry_price=entry_price,
                exit_price=exit_exec,
                bars_held=held,
                reason_entry=str(position["reason_entry"]),
                reason_exit=reason_exit,
                gross_pnl=gross,
                fee=fee,
                net_pnl=net,
            )
        )

        equity_curve.append(equity)
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak
            max_drawdown = max(max_drawdown, dd)

        if signal.action in (SignalAction.BUY, SignalAction.SELL) and signal.size > 0:
            re_entry_exec = _execution_price(
                raw_price=next_open,
                side=signal.action,
                is_entry=True,
                slippage_ratio=slippage_ratio,
                spread_ratio=spread_ratio,
            )
            position = {
                "side": signal.action,
                "qty": float(signal.size),
                "entry_price": re_entry_exec,
                "entry_idx": i + 1,
                "entry_ts": _safe_ts(next_bar.get("ts")),
                "reason_entry": signal.reason.splitlines()[0] if signal.reason else signal.action.value,
            }
        else:
            position = None

    if position is not None:
        last_bar = features.iloc[-1]
        exit_price = float(last_bar.get("close", 0.0) or 0.0)
        if exit_price > 0:
            qty = float(position["qty"])
            entry_price = float(position["entry_price"])
            exit_exec = _execution_price(
                raw_price=exit_price,
                side=position["side"],
                is_entry=False,
                slippage_ratio=slippage_ratio,
                spread_ratio=spread_ratio,
            )
            gross = _pnl(position["side"], qty, entry_price, exit_exec)
            fee = (entry_price + exit_exec) * qty * max(0.0, fee_rate)
            net = gross - fee
            equity += net
            held = (len(features) - 1) - int(position["entry_idx"])
            trades.append(
                BacktestTrade(
                    inst_id=inst_id,
                    timeframe=timeframe,
                    side=position["side"].value,
                    qty=qty,
                    entry_ts=str(position["entry_ts"]),
                    exit_ts=_safe_ts(last_bar.get("ts")),
                    entry_price=entry_price,
                    exit_price=exit_exec,
                    bars_held=max(0, held),
                    reason_entry=str(position["reason_entry"]),
                    reason_exit="end_of_data",
                    gross_pnl=gross,
                    fee=fee,
                    net_pnl=net,
                )
            )
            equity_curve.append(equity)
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak
                max_drawdown = max(max_drawdown, dd)

    total = len(trades)
    wins = len([item for item in trades if item.net_pnl > 0])
    losses = len([item for item in trades if item.net_pnl <= 0])
    gross_sum = sum(item.gross_pnl for item in trades)
    fee_sum = sum(item.fee for item in trades)
    net_sum = sum(item.net_pnl for item in trades)
    avg_trade = net_sum / total if total else 0.0
    profit_win = sum(item.net_pnl for item in trades if item.net_pnl > 0)
    profit_loss = abs(sum(item.net_pnl for item in trades if item.net_pnl < 0))
    if profit_loss <= 1e-12:
        profit_factor = float("inf") if profit_win > 0 else 0.0
    else:
        profit_factor = profit_win / profit_loss

    summary = BacktestSummary(
        inst_id=inst_id,
        timeframe=timeframe,
        bars=len(features),
        warmup=warmup,
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate=(wins / total) if total else 0.0,
        gross_pnl=gross_sum,
        fee_total=fee_sum,
        net_pnl=net_sum,
        avg_trade_pnl=avg_trade,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        initial_equity=initial_equity,
        final_equity=equity,
    )
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_hold_bars": max_hold_bars,
        "fee_rate": fee_rate,
        "slippage_ratio": slippage_ratio,
        "spread_ratio": spread_ratio,
        "leverage": leverage,
        "max_position": max_position,
    }
    return BacktestResult(summary=summary, trades=trades, metadata=metadata)


__all__ = [
    "BacktestResult",
    "BacktestSummary",
    "BacktestTrade",
    "run_backtest_from_features",
]
