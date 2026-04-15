"""策略核心路径测试（回归：分析观点字符串拼接）。"""

from __future__ import annotations

import pandas as pd

from core.analysis.market import (
    LevelAssessment,
    MarketAnalysis,
    MomentumAssessment,
    RiskAssessment,
    TrendAssessment,
)
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


def test_analysis_interpreter_can_build_view_from_market_analysis() -> None:
    strategy = Strategy()
    market_analysis = MarketAnalysis(
        text="deterministic",
        summary="summary",
        history_hint="history",
        trend=TrendAssessment(direction="bullish", strength=0.78, label="强势上涨"),
        momentum=MomentumAssessment(score=0.42, label="bullish", rsi=67.0),
        levels=LevelAssessment(supports=[101.0], resistances=[108.0]),
        risk=RiskAssessment(factors=["高波动率"], volatility_ratio=0.04, regime="hot"),
    )

    view = strategy.analysis_interpreter.from_market_analysis(market_analysis)

    assert view.action == SignalAction.BUY
    assert view.confidence > 0.6
    assert "强势上涨" in view.reason
    assert "高波动率" in view.risk


def test_generate_signal_prefers_structured_market_analysis_when_text_is_unstructured(monkeypatch) -> None:
    strategy = Strategy()
    features = _build_features()
    context = StrategyContext(inst_id="BTC-USDT-SWAP", timeframe="5m", max_position=0.01)
    market_analysis = MarketAnalysis(
        text="plain deterministic text",
        summary="summary",
        history_hint="history",
        trend=TrendAssessment(direction="bullish", strength=0.82, label="强势上涨"),
        momentum=MomentumAssessment(score=0.38, label="bullish", rsi=64.0),
        levels=LevelAssessment(supports=[101.0], resistances=[109.0]),
        risk=RiskAssessment(factors=["接近阻力位"], volatility_ratio=0.03, regime="normal"),
    )

    signals = (
        ObjectiveSignal("indicator", SignalAction.HOLD, 0.4, "indicator"),
    )
    monkeypatch.setattr(strategy.signal_generator, "build", lambda *_args, **_kwargs: signals)
    monkeypatch.setattr(strategy.signal_generator, "liquidity_snapshot", lambda _features: (True, None))
    monkeypatch.setattr(strategy.signal_generator, "volatility_regime", lambda _higher: (1.0, None))
    monkeypatch.setattr(strategy.position_sizer, "size", lambda **_kwargs: 0.01)

    result = strategy.generate_signal(
        context,
        features,
        "plain deterministic text",
        None,
        market_analysis=market_analysis,
    )

    assert result.analysis_view.action == SignalAction.BUY
    assert "结构化分析" in result.trade_signal.reason
    assert "强势上涨" in result.trade_signal.reason


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


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "close": 100.0,
                "open": 99.6,
                "high": 100.3,
                "low": 99.4,
                "volume": 1000.0,
                "volume_usd": 100000.0,
                "returns": 0.001,
                "rsi": 55.0,
                "ema_fast": 99.8,
                "ema_slow": 99.4,
                "macd": 0.2,
                "macd_signal": 0.15,
                "macd_hist": 0.05,
                "atr": 1.0,
                "bb_high": 102.0,
                "bb_low": 98.0,
                "bb_width": 0.03,
                "obv": 10000.0,
                "mfi": 56.0,
            }
            for _ in range(90)
        ]
    )


def test_generate_signal_keeps_hold_without_template_even_when_support_plugin_is_directional(monkeypatch) -> None:
    strategy = Strategy()
    context = StrategyContext(inst_id="BTC-USDT-SWAP", timeframe="5m", max_position=0.01)
    features = _features()

    monkeypatch.setattr(
        strategy.signal_generator,
        "build",
        lambda *_args, **_kwargs: (
            ObjectiveSignal("indicator", SignalAction.HOLD, 0.4, "hold"),
            ObjectiveSignal("volume_breakout", SignalAction.BUY, 0.82, "breakout"),
        ),
    )

    result = strategy.generate_signal(context, features, '{"action":"hold","confidence":0.5,"reason":"flat"}', None)

    assert result.trade_signal.action == SignalAction.HOLD
    assert result.entry_template is None


def test_generate_signal_records_gate_reason_and_template_name() -> None:
    strategy = Strategy()
    context = StrategyContext(inst_id="BTC-USDT-SWAP", timeframe="5m", max_position=0.01)
    features = _features()
    higher_features = {"1H": _features().tail(10).assign(adx=22.0, rsi=57.0)}

    result = strategy.generate_signal(context, features, '{"action":"buy","confidence":0.6,"reason":"ok"}', higher_features)

    assert result.gate_decision is not None
    assert result.trade_signal.reason
