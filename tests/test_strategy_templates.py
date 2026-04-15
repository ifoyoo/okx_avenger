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
                "volume": 910.0,
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

