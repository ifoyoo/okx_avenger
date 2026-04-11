"""ObjectiveSignalGenerator 新增策略信号测试。"""

from __future__ import annotations

import pandas as pd

from core.models import SignalAction
from core.strategy.core import ObjectiveSignalGenerator


def _base_frame(n: int = 80) -> pd.DataFrame:
    rows = []
    for i in range(n):
        close = 100 + i * 0.1
        rows.append(
            {
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.5,
                "close": close,
                "volume": 1000.0,
                "volume_usd": close * 1000.0,
                "returns": 0.001,
                "rsi": 55.0,
                "ema_fast": close - 0.1,
                "ema_slow": close - 0.3,
                "atr": 1.2,
                "macd": 0.2,
                "macd_signal": 0.1,
                "macd_hist": 0.1,
                "bb_high": close + 2.0,
                "bb_low": close - 2.0,
                "bb_width": 0.04,
                "obv": 10000 + i * 10,
                "mfi": 55.0,
                "adx": 25.0,
            }
        )
    return pd.DataFrame(rows)


def test_ma_golden_cross_signal_buy() -> None:
    gen = ObjectiveSignalGenerator()
    df = _base_frame(40)
    df.loc[:36, "ema_fast"] = df.loc[:36, "ema_slow"] - 0.2
    df.loc[37, "ema_fast"] = df.loc[37, "ema_slow"] - 0.05
    df.loc[38, "ema_fast"] = df.loc[38, "ema_slow"] + 0.02
    df.loc[39, "ema_fast"] = df.loc[39, "ema_slow"] + 0.12
    df.loc[39, "volume"] = 1800

    signal = gen._ma_golden_cross_signal(df)

    assert signal is not None
    assert signal.name == "ma_golden_cross"
    assert signal.action == SignalAction.BUY


def test_shrink_pullback_signal_buy() -> None:
    gen = ObjectiveSignalGenerator()
    df = _base_frame(35)
    df["ema_slow"] = df["close"] - 1.2
    df["ema_fast"] = df["close"] - 0.2
    df.loc[34, "close"] = df.loc[34, "ema_fast"] * 1.003
    df.loc[34, "volume"] = 500  # 缩量
    df.loc[29:33, "volume"] = 1000

    signal = gen._shrink_pullback_signal(df)

    assert signal is not None
    assert signal.name == "shrink_pullback"
    assert signal.action == SignalAction.BUY


def test_volume_breakout_signal_buy() -> None:
    gen = ObjectiveSignalGenerator()
    df = _base_frame(45)
    df.loc[:43, "high"] = 110.0
    df.loc[:43, "close"] = 108.0
    df.loc[44, "close"] = 115.0
    df.loc[44, "high"] = 116.0
    df.loc[44, "volume"] = 3000.0

    signal = gen._price_volume_breakout_signal(df)

    assert signal is not None
    assert signal.name == "volume_breakout"
    assert signal.action == SignalAction.BUY


def test_box_oscillation_signal_buy() -> None:
    gen = ObjectiveSignalGenerator()
    df = _base_frame(70)
    # 构造箱体：90~100，当前靠近箱底
    for i in range(70):
        phase = i % 10
        low = 90.0 + phase * 0.2
        high = 100.0 - phase * 0.1
        close = (low + high) / 2
        df.loc[i, "low"] = low
        df.loc[i, "high"] = high
        df.loc[i, "close"] = close
        df.loc[i, "open"] = close - 0.1
    df.loc[69, "close"] = 90.7
    df.loc[69, "volume"] = 900.0

    signal = gen._box_oscillation_signal(df)

    assert signal is not None
    assert signal.name == "box_oscillation"
    assert signal.action == SignalAction.BUY


def test_one_yang_three_yin_signal_buy() -> None:
    gen = ObjectiveSignalGenerator()
    df = _base_frame(10)
    pattern = [
        # open, high, low, close, volume
        (100.0, 104.0, 99.0, 103.0, 2000.0),
        (102.2, 102.6, 100.5, 101.2, 1300.0),
        (101.6, 102.0, 100.6, 100.9, 1100.0),
        (101.3, 101.8, 100.4, 100.8, 900.0),
        (101.2, 104.5, 100.9, 104.2, 1800.0),
    ]
    start = len(df) - 5
    for idx, (o, h, l, c, v) in enumerate(pattern):
        i = start + idx
        df.loc[i, "open"] = o
        df.loc[i, "high"] = h
        df.loc[i, "low"] = l
        df.loc[i, "close"] = c
        df.loc[i, "volume"] = v

    signal = gen._one_yang_three_yin_signal(df)

    assert signal is not None
    assert signal.name == "one_yang_three_yin"
    assert signal.action == SignalAction.BUY

