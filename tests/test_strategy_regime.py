import pandas as pd

from core.strategy import evaluate_higher_timeframe_gate


def _frame(
    close: float,
    fast: float,
    slow: float,
    rsi: float,
    adx: float,
    *,
    prev_close_delta: float = -1.0,
    prev_fast_delta: float = -0.2,
    prev_slow_delta: float = -0.1,
    prev_rsi_delta: float = -1.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "close": close + prev_close_delta,
                "ema_fast": fast + prev_fast_delta,
                "ema_slow": slow + prev_slow_delta,
                "rsi": rsi + prev_rsi_delta,
                "adx": adx,
            },
            {"close": close, "ema_fast": fast, "ema_slow": slow, "rsi": rsi, "adx": adx},
        ]
    )


def test_evaluate_higher_timeframe_gate_allows_breakout_longs_when_trend_is_strong() -> None:
    gate = evaluate_higher_timeframe_gate({"1H": _frame(101.0, 100.8, 100.1, 57.0, 22.0)})

    assert gate.allow_long is True
    assert gate.allow_breakout_long is True
    assert gate.allow_short is False


def test_evaluate_higher_timeframe_gate_blocks_shorts_without_adx_confirmation() -> None:
    bearish_without_adx = _frame(
        98.0,
        97.6,
        98.4,
        42.0,
        16.0,
        prev_fast_delta=0.4,  # ensures negative ema_fast slope
        prev_slow_delta=0.6,
    )
    bearish_with_adx = _frame(
        98.0,
        97.6,
        98.4,
        42.0,
        22.0,
        prev_fast_delta=0.4,
        prev_slow_delta=0.6,
    )

    gate = evaluate_higher_timeframe_gate({"1H": bearish_without_adx})
    gate_confirmed = evaluate_higher_timeframe_gate({"1H": bearish_with_adx})

    assert gate.allow_short is False
    assert gate.allow_long is False
    assert gate.reason_code == "no_trade"
    assert gate_confirmed.allow_short is True
    assert gate_confirmed.allow_long is False
