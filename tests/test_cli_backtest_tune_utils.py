"""CLI 回测调参辅助函数测试。"""

from __future__ import annotations

import pandas as pd

from cli_app.backtest_helpers import _market_regime_bucket, _plugin_score, _scores_to_weights


def test_scores_to_weights_monotonic() -> None:
    scores = {"a": 0.1, "b": 0.2, "c": 0.3}
    weights = _scores_to_weights(scores)
    assert weights["a"] < weights["b"] < weights["c"]
    assert 0.69 <= weights["a"] <= 1.51
    assert 0.69 <= weights["c"] <= 1.51


def test_scores_to_weights_flat() -> None:
    weights = _scores_to_weights({"a": 1.0, "b": 1.0})
    assert weights["a"] == 1.0
    assert weights["b"] == 1.0


def test_plugin_score_positive_case() -> None:
    summary = {
        "net_pnl": 120.0,
        "win_rate": 0.62,
        "max_drawdown": 0.08,
        "total_trades": 20,
    }
    score = _plugin_score(summary, 10_000.0)
    assert isinstance(score, float)
    assert score > -1.0


def test_market_regime_bucket() -> None:
    df_low = pd.DataFrame(
        [{"close": 100.0 + i * 0.1, "atr": 0.2} for i in range(40)]
    )
    df_high = pd.DataFrame(
        [{"close": 100.0 + i * 0.1, "atr": 3.0} for i in range(40)]
    )
    assert _market_regime_bucket(df_low) == "low_vol"
    assert _market_regime_bucket(df_high) == "high_vol"
