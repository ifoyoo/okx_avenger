"""行情数据处理与指标计算."""

from __future__ import annotations

import json
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
DEFAULT_INDICATOR_WINDOWS = {
    "rsi": 14,
    "ema_fast": 12,
    "ema_slow": 26,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_sign": 9,
    "atr": 14,
    "bb": 20,
    "mfi": 14,
    "stoch": 14,
    "cci": 20,
    "adx": 14,
    "williams": 14,
    "ichimoku1": 9,
    "ichimoku2": 26,
    "ichimoku3": 52,
}


def _to_int(value: object, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed <= 0:
        return fallback
    return parsed


def _resolve_indicator_windows(inst_id: str, timeframe: str, overrides_raw: str) -> dict[str, int]:
    windows = dict(DEFAULT_INDICATOR_WINDOWS)
    text = str(overrides_raw or "").strip()
    if not text:
        return windows
    try:
        payload = json.loads(text)
    except Exception:
        return windows
    if not isinstance(payload, dict):
        return windows

    def _apply(node: object) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            key_text = str(key or "").strip()
            if key_text not in windows:
                continue
            windows[key_text] = _to_int(value, windows[key_text])

    _apply(payload.get("default"))
    if timeframe:
        _apply(payload.get(str(timeframe)))
    inst_tf_key = f"{(inst_id or '').upper()}@{(timeframe or '').lower()}"
    if inst_tf_key:
        _apply(payload.get(inst_tf_key))

    windows["ema_fast"] = max(2, windows["ema_fast"])
    windows["ema_slow"] = max(windows["ema_fast"] + 1, windows["ema_slow"])
    windows["macd_fast"] = max(2, windows["macd_fast"])
    windows["macd_slow"] = max(windows["macd_fast"] + 1, windows["macd_slow"])
    windows["macd_sign"] = max(2, windows["macd_sign"])
    windows["ichimoku1"] = max(2, windows["ichimoku1"])
    windows["ichimoku2"] = max(windows["ichimoku1"] + 1, windows["ichimoku2"])
    windows["ichimoku3"] = max(windows["ichimoku2"] + 1, windows["ichimoku3"])
    return windows


def candles_to_dataframe(
    raw_candles: Iterable[Iterable[str]],
    *,
    timeframe: str = "",
    inst_id: str = "",
    indicator_overrides: str = "",
) -> pd.DataFrame:
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
    windows = _resolve_indicator_windows(inst_id=inst_id, timeframe=timeframe, overrides_raw=indicator_overrides)
    df["returns"] = df["close"].pct_change().fillna(0)
    df["rsi"] = RSIIndicator(close=df["close"], window=windows["rsi"]).rsi()
    df["ema_fast"] = EMAIndicator(close=df["close"], window=windows["ema_fast"]).ema_indicator()
    df["ema_slow"] = EMAIndicator(close=df["close"], window=windows["ema_slow"]).ema_indicator()
    macd = MACD(
        close=df["close"],
        window_fast=windows["macd_fast"],
        window_slow=windows["macd_slow"],
        window_sign=windows["macd_sign"],
    )
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    df["atr"] = AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=windows["atr"],
    ).average_true_range()
    bb = BollingerBands(close=df["close"], window=windows["bb"], window_dev=2.0)
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()
    band_range = df["bb_high"] - df["bb_low"]
    close = df["close"].replace(0, pd.NA)
    df["bb_width"] = (band_range / close).fillna(0)
    obv = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"])
    df["obv"] = obv.on_balance_volume()
    mfi = MFIIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        volume=df["volume"],
        window=windows["mfi"],
    )
    df["mfi"] = mfi.money_flow_index()

    # 新增指标：Stochastic Oscillator
    stoch = StochasticOscillator(
        high=df["high"], low=df["low"], close=df["close"],
        window=windows["stoch"], smooth_window=3
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # 新增指标：KDJ (基于 Stochastic 派生)
    df["kdj_j"] = 3 * df["stoch_k"] - 2 * df["stoch_d"]

    # 新增指标：CCI (商品通道指标)
    cci = CCIIndicator(
        high=df["high"], low=df["low"], close=df["close"],
        window=windows["cci"]
    )
    df["cci"] = cci.cci()

    # 新增指标：ADX (趋势强度指标)
    adx = ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"],
        window=windows["adx"]
    )
    df["adx"] = adx.adx()
    df["adx_pos"] = adx.adx_pos()
    df["adx_neg"] = adx.adx_neg()

    # 新增指标：Williams %R
    williams = WilliamsRIndicator(
        high=df["high"], low=df["low"], close=df["close"],
        lbp=windows["williams"]
    )
    df["williams_r"] = williams.williams_r()

    # 新增指标：Ichimoku (一目均衡表)
    ichimoku = IchimokuIndicator(
        high=df["high"], low=df["low"],
        window1=windows["ichimoku1"],
        window2=windows["ichimoku2"],
        window3=windows["ichimoku3"],
    )
    df["ichimoku_conv"] = ichimoku.ichimoku_conversion_line()
    df["ichimoku_base"] = ichimoku.ichimoku_base_line()
    df["ichimoku_a"] = ichimoku.ichimoku_a()
    df["ichimoku_b"] = ichimoku.ichimoku_b()

    df.bfill(inplace=True)
    df.ffill(inplace=True)
    return df
