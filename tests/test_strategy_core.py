"""策略核心路径测试（回归：分析观点字符串拼接）。"""

from __future__ import annotations

import pandas as pd

from core.models import SignalAction, StrategyContext
from core.strategy.core import AnalysisView, Strategy
from core.strategy.signals import ObjectiveSignal


def _build_features(rows: int = 80) -> pd.DataFrame:
    data = []
    for i in range(rows):
        close = 100 + i * 0.2
        data.append(
            {
                "close": close,
                "open": close - 0.3,
                "high": close + 0.5,
                "low": close - 0.6,
                "volume": 1000 + i * 5,
                "volume_usd": (1000 + i * 5) * close,
                "returns": 0.001,
                "rsi": 50.0,
                "ema_fast": close - 0.1,
                "ema_slow": close - 0.4,
                "macd": 0.2,
                "macd_signal": 0.15,
                "macd_hist": 0.05,
                "atr": 1.1,
                "bb_high": close + 2.0,
                "bb_low": close - 2.0,
                "bb_width": 0.04,
                "obv": 10000 + i * 20,
                "mfi": 55.0,
            }
        )
    return pd.DataFrame(data)


def test_generate_signal_reason_contains_analysis_action_uppercase() -> None:
    strategy = Strategy()
    features = _build_features()
    context = StrategyContext(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        max_position=0.01,
    )
    analysis_text = '{"action":"buy","confidence":0.8,"reason":"test-analysis"}'

    result = strategy.generate_signal(context, features, analysis_text, None)

    assert "分析观点：BUY" in result.trade_signal.reason
    assert "test-analysis" in result.trade_signal.reason


def test_analysis_interpreter_parse_returns_analysis_view() -> None:
    strategy = Strategy()
    view = strategy.analysis_interpreter.parse('{"action":"sell","confidence":0.7,"reason":"x"}')
    assert isinstance(view, AnalysisView)
    assert view.action.value == "sell"


def test_generate_signal_reason_contains_arb_tag(monkeypatch) -> None:
    strategy = Strategy()
    features = _build_features()
    context = StrategyContext(inst_id="BTC-USDT-SWAP", timeframe="5m", max_position=0.01)

    signals = (
        ObjectiveSignal("indicator", SignalAction.BUY, 0.72, "indicator"),
        ObjectiveSignal("volume_pressure", SignalAction.SELL, 0.91, "vp"),
        ObjectiveSignal("box_oscillation", SignalAction.SELL, 0.86, "box"),
    )
    monkeypatch.setattr(strategy.signal_generator, "build", lambda *_args, **_kwargs: signals)
    monkeypatch.setattr(strategy.signal_generator, "liquidity_snapshot", lambda _features: (True, None))
    monkeypatch.setattr(strategy.signal_generator, "volatility_regime", lambda _higher: (1.0, None))
    monkeypatch.setattr(strategy.position_sizer, "size", lambda **_kwargs: 0.01)

    result = strategy.generate_signal(
        context,
        features,
        '{"action":"buy","confidence":0.7,"reason":"analysis"}',
        None,
    )

    assert "[arb]" in result.trade_signal.reason
