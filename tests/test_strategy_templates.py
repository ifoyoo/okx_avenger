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


def test_evaluate_entry_template_ignores_gate_veto_when_template_matches() -> None:
    gate = HigherTimeframeGate(False, True, False, True, "bearish", "allow_short", "1H bearish")

    match = evaluate_entry_template(gate=gate, features=_features())

    assert match is not None
    assert match.template_name == "pullback_long"


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


def test_evaluate_entry_template_uses_previous_confirmed_candle_when_tail_bar_is_open() -> None:
    gate = HigherTimeframeGate(True, False, True, False, "bullish", "allow_long", "1H bullish")
    features = pd.DataFrame(
        [
            {"close": 100.0, "ema_fast": 99.6, "ema_slow": 99.2, "volume": 1000.0, "rsi": 54.0, "high": 100.2, "low": 99.4, "confirm": "1"},
            {"close": 99.7, "ema_fast": 99.7, "ema_slow": 99.3, "volume": 880.0, "rsi": 50.0, "high": 99.9, "low": 99.5, "confirm": "1"},
            {"close": 100.1, "ema_fast": 99.9, "ema_slow": 99.4, "volume": 870.0, "rsi": 56.0, "high": 100.3, "low": 99.8, "confirm": "1"},
            {"close": 100.8, "ema_fast": 100.8, "ema_slow": 99.4, "volume": 10.0, "rsi": 72.0, "high": 100.9, "low": 100.6, "confirm": "0"},
        ]
    )

    match = evaluate_entry_template(gate=gate, features=features)

    assert match is not None
    assert match.template_name == "pullback_long"


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


def test_evaluate_entry_template_returns_none_on_missing_required_columns() -> None:
    gate = HigherTimeframeGate(True, False, True, False, "bullish", "allow_long", "1H bullish")

    # Missing rsi column; without a strict required-columns guard this could match pullback_long.
    features = pd.DataFrame(
        [
            {"close": 100.0, "ema_fast": 99.6, "ema_slow": 99.2, "volume": 1000.0, "high": 100.2, "low": 99.4},
            {"close": 99.7, "ema_fast": 99.7, "ema_slow": 99.3, "volume": 880.0, "high": 99.9, "low": 99.5},
            {"close": 100.1, "ema_fast": 99.9, "ema_slow": 99.4, "volume": 870.0, "high": 100.3, "low": 99.8},
        ]
    )

    match = evaluate_entry_template(gate=gate, features=features)

    assert match is None


def test_evaluate_entry_template_returns_none_on_non_numeric_feature_value() -> None:
    gate = HigherTimeframeGate(True, False, True, False, "bullish", "allow_long", "1H bullish")

    features = pd.DataFrame(
        [
            {"close": 100.0, "ema_fast": 99.6, "ema_slow": 99.2, "volume": 1000.0, "rsi": 54.0, "high": 100.2, "low": 99.4},
            {"close": 99.7, "ema_fast": 99.7, "ema_slow": 99.3, "volume": 880.0, "rsi": 50.0, "high": 99.9, "low": 99.5},
            # Malformed ema_fast should not raise; it should return None.
            {"close": 100.1, "ema_fast": "bad", "ema_slow": 99.4, "volume": 870.0, "rsi": 56.0, "high": 100.3, "low": 99.8},
        ]
    )

    match = evaluate_entry_template(gate=gate, features=features)

    assert match is None


def test_templates_are_exported_via_strategy_package() -> None:
    from core.strategy import EntryTemplateMatch, evaluate_entry_template  # noqa: F401
