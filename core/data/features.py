"""行情数据处理与指标计算."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator
from ta.trend import EMAIndicator, MACD, CCIIndicator, ADXIndicator, IchimokuIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator, MFIIndicator


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
    obv = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"])
    df["obv"] = obv.on_balance_volume()
    mfi = MFIIndicator(high=df["high"], low=df["low"], close=df["close"], volume=df["volume"], window=14)
    df["mfi"] = mfi.money_flow_index()

    # 新增指标：Stochastic Oscillator
    stoch = StochasticOscillator(
        high=df["high"], low=df["low"], close=df["close"],
        window=14, smooth_window=3
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # 新增指标：KDJ (基于 Stochastic 派生)
    df["kdj_j"] = 3 * df["stoch_k"] - 2 * df["stoch_d"]

    # 新增指标：CCI (商品通道指标)
    cci = CCIIndicator(
        high=df["high"], low=df["low"], close=df["close"],
        window=20
    )
    df["cci"] = cci.cci()

    # 新增指标：ADX (趋势强度指标)
    adx = ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"],
        window=14
    )
    df["adx"] = adx.adx()
    df["adx_pos"] = adx.adx_pos()
    df["adx_neg"] = adx.adx_neg()

    # 新增指标：Williams %R
    williams = WilliamsRIndicator(
        high=df["high"], low=df["low"], close=df["close"],
        lbp=14
    )
    df["williams_r"] = williams.williams_r()

    # 新增指标：Ichimoku (一目均衡表)
    ichimoku = IchimokuIndicator(
        high=df["high"], low=df["low"],
        window1=9, window2=26, window3=52
    )
    df["ichimoku_conv"] = ichimoku.ichimoku_conversion_line()
    df["ichimoku_base"] = ichimoku.ichimoku_base_line()
    df["ichimoku_a"] = ichimoku.ichimoku_a()
    df["ichimoku_b"] = ichimoku.ichimoku_b()

    df.bfill(inplace=True)
    df.ffill(inplace=True)
    return df
