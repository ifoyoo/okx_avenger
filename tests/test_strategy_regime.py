import pandas as pd

from core.strategy.regime import evaluate_higher_timeframe_gate


def _frame(close: float, fast: float, slow: float, rsi: float, adx: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"close": close - 1, "ema_fast": fast - 0.2, "ema_slow": slow - 0.1, "rsi": rsi - 1, "adx": adx},
            {"close": close, "ema_fast": fast, "ema_slow": slow, "rsi": rsi, "adx": adx},
        ]
    )


def test_evaluate_higher_timeframe_gate_allows_breakout_longs_when_trend_is_strong() -> None:
    gate = evaluate_higher_timeframe_gate({"1H": _frame(101.0, 100.8, 100.1, 57.0, 22.0)})

    assert gate.allow_long is True
    assert gate.allow_breakout_long is True
    assert gate.allow_short is False


def test_evaluate_higher_timeframe_gate_blocks_shorts_without_adx_confirmation() -> None:
    gate = evaluate_higher_timeframe_gate({"1H": _frame(98.0, 97.6, 98.4, 42.0, 16.0)})

    assert gate.allow_short is False
    assert gate.allow_long is False
    assert gate.reason_code == "no_trade"

