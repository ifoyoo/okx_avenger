"""行情数据处理与指标计算."""

from __future__ import annotations

from typing import Iterable, List

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands


CANDLE_COLUMNS = [
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "volume_currency",
    "volume_usd",
    "confirm",
]


def candles_to_dataframe(raw_candles: Iterable[Iterable[str]]) -> pd.DataFrame:
    """将 OKX K 线转换为带指标的 DataFrame."""

    rows = list(raw_candles)
    if not rows:
        raise ValueError("未获取到任何 K 线数据")
    df = pd.DataFrame(rows, columns=CANDLE_COLUMNS)
    numeric = ["open", "high", "low", "close", "volume", "volume_currency", "volume_usd"]
    df[numeric] = df[numeric].astype(float)
    ts_numeric = pd.to_numeric(df["ts"], errors="coerce")
    # OKX 理论上返回毫秒，但部分合约可能出现微秒/纳秒，需要折算为毫秒避免溢出。
    abs_ts = ts_numeric.abs()
    ns_mask = abs_ts > 1e17  # 纳秒级时间戳
    us_mask = (abs_ts > 1e13) & ~ns_mask  # 微秒级时间戳
    if ns_mask.any():
        ts_numeric.loc[ns_mask] = ts_numeric.loc[ns_mask] // 1_000_000
    if us_mask.any():
        ts_numeric.loc[us_mask] = ts_numeric.loc[us_mask] // 1_000
    df["ts"] = pd.to_datetime(ts_numeric, unit="ms", utc=True, errors="coerce")
    df.dropna(subset=["ts"], inplace=True)
    df.sort_values("ts", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df["returns"] = df["close"].pct_change().fillna(0)
    df["rsi"] = RSIIndicator(close=df["close"], window=14).rsi()
    df["ema_fast"] = EMAIndicator(close=df["close"], window=12).ema_indicator()
    df["ema_slow"] = EMAIndicator(close=df["close"], window=26).ema_indicator()
    macd = MACD(close=df["close"], window_fast=12, window_slow=26, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    df["atr"] = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    ).average_true_range()
    bb = BollingerBands(close=df["close"], window=20, window_dev=2.0)
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()
    band_range = df["bb_high"] - df["bb_low"]
    close = df["close"].replace(0, pd.NA)
    df["bb_width"] = (band_range / close).fillna(0)
    df.bfill(inplace=True)
    df.ffill(inplace=True)
    return df
