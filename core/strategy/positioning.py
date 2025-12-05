"""Position sizing utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .models import SignalAction, StrategyContext


VOL_TARGET = 0.015
GLOBAL_POSITION_CAP = 0.05


@dataclass
class PositionSizerConfig:
    """Config for dynamic position sizing."""

    global_cap: float = GLOBAL_POSITION_CAP
    vol_target: float = VOL_TARGET
    max_equity_risk: float = 0.02
    max_balance_risk: float = 0.05
    min_floor_ratio: float = 0.2
    env_floor: float = 0.3


class PositionSizer:
    """Translate signal confidence and risk inputs into executable size."""

    def __init__(self, config: Optional[PositionSizerConfig] = None) -> None:
        self.config = config or PositionSizerConfig()

    def size(
        self,
        context: StrategyContext,
        latest: pd.Series,
        confidence: float,
        action: SignalAction,
        trend_bias: SignalAction = SignalAction.HOLD,
        env_factor: float = 1.0,
    ) -> float:
        base = max(context.max_position or 0.001, 0.0001)
        close = float(latest.get("close", 0.0))
        atr = float(latest.get("atr", 0.0))
        atr_pct = atr / close if close else 0.0
        leverage = max(1.0, getattr(context, "leverage", 1.0) or 1.0)
        if close > 0 and context.account_equity:
            max_by_equity = (context.account_equity * self.config.max_equity_risk * leverage) / close
            if max_by_equity > 0:
                base = min(base, max_by_equity)
        if close > 0 and context.available_balance:
            max_by_balance = (context.available_balance * self.config.max_balance_risk * leverage) / close
            if max_by_balance > 0:
                base = min(base, max_by_balance)
        if atr_pct <= 0:
            vol_factor = 1.0
        else:
            vol_factor = min(1.5, max(0.4, self.config.vol_target / atr_pct))
        dynamic = base * confidence * vol_factor * max(self.config.env_floor, env_factor)
        if trend_bias != SignalAction.HOLD:
            if trend_bias == action:
                dynamic *= 1.1
            else:
                dynamic *= 0.75
        floor = base * self.config.min_floor_ratio
        size = min(self.config.global_cap, max(dynamic, floor))
        return max(size, 0.0)


__all__ = ["PositionSizer", "PositionSizerConfig", "VOL_TARGET", "GLOBAL_POSITION_CAP"]
