import pandas as pd

from core.strategy.regime import HigherTimeframeGate
from core.strategy.templates import evaluate_entry_template


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "close": 100.0,
                "ema_fast": 99.6,
                "ema_slow": 99.2,
                "volume": 1000.0,
                "rsi": 54.0,
                "high": 100.2,
                "low": 99.4,
            },
            {
                "close": 99.7,
                "ema_fast": 99.7,
                "ema_slow": 99.3,
                "volume": 880.0,
                "rsi": 50.0,
                "high": 99.9,
                "low": 99.5,
            },
            {
                "close": 100.1,
                "ema_fast": 99.9,
                "ema_slow": 99.4,
                "volume": 870.0,
                "rsi": 56.0,
                "high": 100.3,
                "low": 99.8,
            },
        ]
    )


def test_evaluate_entry_template_matches_pullback_long() -> None:
    gate = HigherTimeframeGate(True, False, True, False, "bullish", "allow_long", "1H bullish")

    match = evaluate_entry_template(gate=gate, features=_features())

    assert match.template_name == "pullback_long"
    assert match.action.value == "buy"


def test_evaluate_entry_template_returns_none_when_gate_blocks_side() -> None:
    gate = HigherTimeframeGate(False, False, False, False, "mixed", "no_trade", "1H mixed")

    match = evaluate_entry_template(gate=gate, features=_features())

    assert match is None


def test_pullback_long_requires_volume_not_higher_than_prev_candle() -> None:
    gate = HigherTimeframeGate(True, False, True, False, "bullish", "allow_long", "1H bullish")

    features = pd.DataFrame(
        [
            {"close": 100.0, "ema_fast": 99.6, "ema_slow": 99.2, "volume": 2000.0, "rsi": 54.0, "high": 100.2, "low": 99.4},
            {"close": 99.7, "ema_fast": 99.7, "ema_slow": 99.3, "volume": 800.0, "rsi": 50.0, "high": 99.9, "low": 99.5},
            # Latest volume is higher than prev; spec requires volume <= prev_volume to match pullback_long.
            {"close": 100.1, "ema_fast": 99.9, "ema_slow": 99.4, "volume": 900.0, "rsi": 56.0, "high": 100.3, "low": 99.8},
        ]
    )

    match = evaluate_entry_template(gate=gate, features=features)

    assert match is None


def test_pullback_long_proximity_denominator_uses_raw_ema_fast_not_abs() -> None:
    gate = HigherTimeframeGate(True, False, True, False, "bullish", "allow_long", "1H bullish")

    # With a negative ema_fast, the spec's denominator is max(ema_fast, 1e-9) which becomes 1e-9,
    # making the proximity ratio enormous and preventing a pullback_long match.
    features = pd.DataFrame(
        [
            {"close": -100.4, "ema_fast": -100.2, "ema_slow": -100.5, "volume": 1000.0, "rsi": 55.0, "high": -100.1, "low": -100.6},
            {"close": -100.3, "ema_fast": -100.1, "ema_slow": -100.4, "volume": 900.0, "rsi": 54.0, "high": -100.2, "low": -100.5},
            {"close": -100.3, "ema_fast": -100.0, "ema_slow": -100.3, "volume": 800.0, "rsi": 56.0, "high": -100.2, "low": -100.4},
        ]
    )

    match = evaluate_entry_template(gate=gate, features=features)

    assert match is None
