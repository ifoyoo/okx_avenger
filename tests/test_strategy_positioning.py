from __future__ import annotations

import pandas as pd
import pytest

from core.models import SignalAction, StrategyContext
from core.strategy.positioning import PositionSizer


def test_position_sizer_applies_smaller_default_size_to_shorts() -> None:
    sizer = PositionSizer()
    context = StrategyContext(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        max_position=1.0,
        leverage=5.0,
        account_equity=1000.0,
        available_balance=1000.0,
    )
    latest = pd.Series({"close": 1000.0, "atr": 20.0})

    long_size = sizer.size(context=context, latest=latest, confidence=1.0, action=SignalAction.BUY)
    short_size = sizer.size(context=context, latest=latest, confidence=1.0, action=SignalAction.SELL)

    assert short_size == pytest.approx(long_size * 0.8, rel=1e-6)


def test_position_sizer_targets_point_six_percent_initial_risk_when_stop_distance_is_large() -> None:
    sizer = PositionSizer()
    context = StrategyContext(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        max_position=1.0,
        leverage=5.0,
        account_equity=1000.0,
        available_balance=1000.0,
    )
    latest = pd.Series({"close": 1000.0, "atr": 200.0})

    size = sizer.size(context=context, latest=latest, confidence=1.0, action=SignalAction.BUY)

    assert size == pytest.approx(6.0 / (200.0 * 1.1), rel=0.05)


def test_position_sizer_allows_context_cap_above_legacy_global_cap() -> None:
    sizer = PositionSizer()
    context = StrategyContext(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        max_position=0.25,
        leverage=5.0,
        account_equity=1000.0,
        available_balance=1000.0,
    )
    latest = pd.Series({"close": 1000.0, "atr": 20.0})

    size = sizer.size(context=context, latest=latest, confidence=1.0, action=SignalAction.BUY)

    assert size == pytest.approx(0.25, rel=1e-6)
