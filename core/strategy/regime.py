from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd


@dataclass(frozen=True)
class HigherTimeframeGate:
    allow_long: bool
    allow_short: bool
    allow_breakout_long: bool
    allow_breakdown_short: bool
    trend_label: str
    reason_code: str
    note: str


def evaluate_higher_timeframe_gate(features_map: Optional[Dict[str, pd.DataFrame]]) -> HigherTimeframeGate:
    if not features_map or "1H" not in features_map or features_map["1H"] is None or features_map["1H"].empty:
        return HigherTimeframeGate(False, False, False, False, "unknown", "no_trade", "missing 1H features")

    frame = features_map["1H"]
    required = {"ema_fast", "ema_slow", "rsi", "adx"}
    missing = sorted(required.difference(set(frame.columns)))
    if missing:
        return HigherTimeframeGate(
            False,
            False,
            False,
            False,
            "unknown",
            "no_trade",
            f"invalid 1H features (missing columns: {', '.join(missing)})",
        )

    latest = frame.iloc[-1]
    try:
        ema_fast = float(latest.get("ema_fast"))
        ema_slow = float(latest.get("ema_slow"))
        rsi = float(latest.get("rsi"))
        adx = float(latest.get("adx"))
    except (TypeError, ValueError):
        return HigherTimeframeGate(False, False, False, False, "unknown", "no_trade", "invalid 1H features")

    slope = 0.0
    if len(frame) >= 2:
        try:
            prev_fast = float(frame["ema_fast"].iloc[-2])
            slope = float(ema_fast - prev_fast)
        except (TypeError, ValueError):
            return HigherTimeframeGate(False, False, False, False, "unknown", "no_trade", "invalid 1H features")

    long_ok = ema_fast > ema_slow and slope > 0 and rsi >= 52.0
    long_breakout_ok = long_ok and adx >= 18.0
    short_ok = ema_fast < ema_slow and slope < 0 and rsi <= 45.0 and adx >= 20.0

    if long_ok:
        return HigherTimeframeGate(True, False, long_breakout_ok, False, "bullish", "allow_long", "1H bullish")
    if short_ok:
        return HigherTimeframeGate(False, True, False, True, "bearish", "allow_short", "1H bearish")
    return HigherTimeframeGate(False, False, False, False, "mixed", "no_trade", "1H mixed")
