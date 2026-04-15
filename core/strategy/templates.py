from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

import pandas as pd

from core.models import SignalAction
from .regime import HigherTimeframeGate


@dataclass(frozen=True)
class EntryTemplateMatch:
    template_name: str
    action: SignalAction
    confidence_floor: float
    note: str


def evaluate_entry_template(*, gate: HigherTimeframeGate, features: pd.DataFrame) -> Optional[EntryTemplateMatch]:
    if features is None or features.empty:
        return None

    required = {"close", "ema_fast", "ema_slow", "volume", "rsi", "high", "low"}
    missing = sorted(required.difference(set(features.columns)))
    if missing:
        return None

    latest = features.iloc[-1]
    prev = features.iloc[-2] if len(features) >= 2 else latest

    try:
        close = float(latest.get("close"))
        ema_fast = float(latest.get("ema_fast"))
        ema_slow = float(latest.get("ema_slow"))
        volume = float(latest.get("volume"))
        rsi = float(latest.get("rsi"))
        prev_volume = float(prev.get("volume"))
        prev_high = float(prev.get("high"))
        prev_low = float(prev.get("low"))
    except (TypeError, ValueError):
        return None

    if not all(math.isfinite(v) for v in (close, ema_fast, ema_slow, volume, rsi, prev_volume, prev_high, prev_low)):
        return None

    near_fast = abs(close - ema_fast) / max(ema_fast, 1e-9) <= 0.004

    if gate.allow_long and ema_fast >= ema_slow and near_fast and volume <= prev_volume and 45.0 <= rsi <= 62.0:
        return EntryTemplateMatch("pullback_long", SignalAction.BUY, 0.58, f"close~{ema_fast:.4f} pullback reclaim")

    if gate.allow_breakout_long and close > prev_high and volume > prev_volume * 1.2 and rsi < 68.0:
        return EntryTemplateMatch("breakout_long", SignalAction.BUY, 0.64, "range break with volume")

    if gate.allow_short and ema_fast <= ema_slow and near_fast and volume <= prev_volume and rsi <= 52.0:
        return EntryTemplateMatch("pullback_short", SignalAction.SELL, 0.58, "failed reclaim into trend")

    if gate.allow_breakdown_short and close < prev_low and volume > prev_volume * 1.2 and rsi > 30.0:
        return EntryTemplateMatch("breakdown_short", SignalAction.SELL, 0.64, "range breakdown with volume")

    return None
