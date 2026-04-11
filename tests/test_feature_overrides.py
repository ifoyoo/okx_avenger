"""特征参数覆盖与分层配置测试。"""

from __future__ import annotations

import json

from core.data.features import _resolve_indicator_windows, candles_to_dataframe


def _raw_candles(rows: int = 90):
    base_ts = 1_700_000_000_000
    data = []
    for i in range(rows):
        close = 100 + i * 0.2
        data.append(
            [
                str(base_ts + i * 60_000),
                f"{close - 0.2:.6f}",
                f"{close + 0.4:.6f}",
                f"{close - 0.5:.6f}",
                f"{close:.6f}",
                "1000",
                "1000",
                f"{1000 * close:.6f}",
                "1",
            ]
        )
    return data


def test_resolve_indicator_windows_layered_override() -> None:
    overrides = json.dumps(
        {
            "default": {"rsi": 10, "ema_fast": 8},
            "5m": {"ema_fast": 6, "ema_slow": 15},
            "BTC-USDT-SWAP@5m": {"ema_fast": 4},
        }
    )
    windows = _resolve_indicator_windows("BTC-USDT-SWAP", "5m", overrides)

    assert windows["rsi"] == 10
    assert windows["ema_fast"] == 4
    assert windows["ema_slow"] == 15


def test_candles_to_dataframe_applies_override() -> None:
    raw = _raw_candles()
    default_df = candles_to_dataframe(raw, timeframe="5m", inst_id="BTC-USDT-SWAP", indicator_overrides="")
    overrides = json.dumps({"5m": {"ema_fast": 4, "ema_slow": 9}})
    custom_df = candles_to_dataframe(raw, timeframe="5m", inst_id="BTC-USDT-SWAP", indicator_overrides=overrides)

    assert len(default_df) == len(custom_df)
    assert abs(float(default_df.iloc[-1]["ema_fast"]) - float(custom_df.iloc[-1]["ema_fast"])) > 1e-9
