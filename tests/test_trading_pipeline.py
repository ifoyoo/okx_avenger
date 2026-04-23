"""交易编排 pipeline 拆分测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
import math

from core.analysis import MarketAnalysis
from core.engine.execution import ExecutionPlan
from core.engine.risk import AccountState, RiskAssessment
from core.engine.trading import (
    AnalysisBundle,
    DataBundle,
    ExecutionBundle,
    RiskBundle,
    StrategyBundle,
    TradingEngine,
)
from core.models import SignalAction, StrategyContext, TradeSignal


def _build_engine() -> TradingEngine:
    settings = SimpleNamespace(
        account=SimpleNamespace(okx_td_mode=None, okx_force_pos_side=None),
        strategy=SimpleNamespace(
            balance_usage_ratio=0.5,
            default_leverage=1.0,
            default_take_profit_upl_ratio=0.0,
            default_stop_loss_upl_ratio=0.0,
        ),
        runtime=SimpleNamespace(data_staleness_seconds=180),
        intel=SimpleNamespace(
            event_gate_mode="degrade",
            event_gate_degrade_threshold=0.72,
            event_gate_block_threshold=0.9,
            event_gate_degrade_confidence_cap=0.45,
            event_gate_degrade_size_ratio=0.5,
        ),
    )
    return TradingEngine(
        okx_client=SimpleNamespace(),
        analyzer=SimpleNamespace(),
        strategy=SimpleNamespace(),
        settings=settings,
    )


def _sample_features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts": "2026-01-01T00:00:00Z",
                "close": 100.0,
                "atr": 1.5,
            }
        ]
    )


def test_run_once_pipeline_order_and_payload(monkeypatch) -> None:
    engine = _build_engine()
    events: list[str] = []
    features = _sample_features()
    risk_signal = TradeSignal(
        action=SignalAction.BUY,
        confidence=0.72,
        reason="risk-passed",
        size=0.01,
    )

    data_step_output = DataBundle(
        features=features,
        higher_features={},
        snapshot={"mock": True},
        account_snapshot={"equity": 1000.0, "available": 600.0},
        risk_note=None,
    )
    analysis_result = MarketAnalysis(
        text="det-analysis",
        summary="det-summary",
        history_hint="det-hint",
    )
    analysis_step_output = AnalysisBundle(
        analysis_result=analysis_result,
        analysis_text="det-analysis",
        strategy_analysis_text='{"action":"buy","confidence":0.72}',
        brain_decision=None,
        market_intel=None,
    )
    strategy_step_output = StrategyBundle(
        context=StrategyContext(inst_id="BTC-USDT-SWAP", timeframe="5m", max_position=0.01),
        strategy_output=SimpleNamespace(
            entry_tier="template-qualified",
            signal_candle_source="latest_confirmed",
            trade_signal=TradeSignal(
                action=SignalAction.BUY,
                confidence=0.72,
                reason="strategy",
                size=0.01,
            )
        ),
    )
    risk_step_output = RiskBundle(
        account_state=AccountState(equity=1000.0, available=600.0),
        risk_assessment=RiskAssessment(
            trade_signal=risk_signal,
            notes=(),
            blocked=False,
            account_state=AccountState(equity=1000.0, available=600.0),
        ),
        signal=risk_signal,
    )
    execution_step_output = ExecutionBundle(
        plan=ExecutionPlan(
            inst_id="BTC-USDT-SWAP",
            action=SignalAction.BUY,
            td_mode="cross",
            pos_side="long",
            order_type="market",
            size=0.01,
            price=None,
            est_slippage=0.0,
        ),
        report=None,
        order={"ordId": "demo"},
    )

    def _fake_data_step(*, inst_id, timeframe, limit, higher_timeframes, account_snapshot):
        events.append("data")
        assert inst_id == "BTC-USDT-SWAP"
        assert timeframe == "5m"
        assert limit == 120
        assert higher_timeframes == ("1H",)
        assert account_snapshot == {"equity": 1000.0, "available": 600.0}
        return data_step_output

    def _fake_analysis_step(
        *,
        inst_id,
        timeframe,
        data_bundle,
        market_intel_query,
        market_intel_coin_id,
        market_intel_aliases,
        positions_snapshot,
        perf_stats,
        daily_stats,
    ):
        events.append("analysis")
        assert inst_id == "BTC-USDT-SWAP"
        assert timeframe == "5m"
        assert data_bundle is data_step_output
        assert market_intel_query is None
        assert market_intel_coin_id is None
        assert market_intel_aliases is None
        assert positions_snapshot == [{"instId": "BTC-USDT-SWAP"}]
        assert perf_stats == {"win_rate": 0.5}
        assert daily_stats == {"date": "2026-04-09"}
        return analysis_step_output

    def _fake_strategy_step(
        *,
        inst_id,
        timeframe,
        dry_run,
        max_position,
        higher_timeframes,
        protection_overrides,
        exchange_protection_enabled,
        data_bundle,
        analysis_bundle,
    ):
        events.append("strategy")
        assert inst_id == "BTC-USDT-SWAP"
        assert timeframe == "5m"
        assert dry_run is True
        assert max_position == 0.01
        assert higher_timeframes == ("1H",)
        assert protection_overrides == {"take_profit": {"mode": "percent", "value": 0.02}}
        assert exchange_protection_enabled is True
        assert data_bundle is data_step_output
        assert analysis_bundle is analysis_step_output
        return strategy_step_output

    def _fake_risk_step(*, inst_id, data_bundle, strategy_output, market_intel, perf_stats, daily_stats):
        events.append("risk")
        assert inst_id == "BTC-USDT-SWAP"
        assert data_bundle is data_step_output
        assert strategy_output is strategy_step_output.strategy_output
        assert market_intel is None
        assert perf_stats == {"win_rate": 0.5}
        assert daily_stats == {"date": "2026-04-09"}
        return risk_step_output

    def _fake_execution_step(*, inst_id, timeframe, trace_id, dry_run, signal, features, max_position):
        events.append("execution")
        assert inst_id == "BTC-USDT-SWAP"
        assert timeframe == "5m"
        assert isinstance(trace_id, str)
        assert len(trace_id) == 16
        assert dry_run is True
        assert signal is risk_signal
        assert features is data_step_output.features
        assert max_position == 0.01
        return execution_step_output

    def _fake_log_decision(*, features, inst_id, timeframe, trace_id, summary, strategy_output, signal):
        events.append("log")
        assert features is data_step_output.features
        assert inst_id == "BTC-USDT-SWAP"
        assert timeframe == "5m"
        assert isinstance(trace_id, str)
        assert len(trace_id) == 16
        assert summary == "det-summary"
        assert strategy_output is strategy_step_output.strategy_output
        assert signal is risk_signal

    monkeypatch.setattr(engine, "_run_data_step", _fake_data_step)
    monkeypatch.setattr(engine, "_run_analysis_step", _fake_analysis_step)
    monkeypatch.setattr(engine, "_run_strategy_step", _fake_strategy_step)
    monkeypatch.setattr(engine, "_run_risk_step", _fake_risk_step)
    monkeypatch.setattr(engine, "_run_execution_step", _fake_execution_step)
    monkeypatch.setattr(engine, "_log_decision", _fake_log_decision)

    result = engine.run_once(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        limit=120,
        dry_run=True,
        max_position=0.01,
        higher_timeframes=("1H",),
        account_snapshot={"equity": 1000.0, "available": 600.0},
        protection_overrides={"take_profit": {"mode": "percent", "value": 0.02}},
        positions_snapshot=[{"instId": "BTC-USDT-SWAP"}],
        perf_stats={"win_rate": 0.5},
        daily_stats={"date": "2026-04-09"},
    )

    assert events == ["data", "analysis", "strategy", "risk", "execution", "log"]
    assert result["analysis"] == "det-analysis"
    assert result["analysis_summary"] == "det-summary"
    assert result["history_hint"] == "det-hint"
    assert isinstance(result["trace_id"], str)
    assert len(result["trace_id"]) == 16
    assert result["signal"] is risk_signal
    assert result["entry_tier"] == "template-qualified"
    assert result["signal_candle_source"] == "latest_confirmed"
    assert result["execution"]["plan"] is execution_step_output.plan
    assert result["order"] == {"ordId": "demo"}


def test_log_decision_records_analysis_gated_and_final_actions(monkeypatch) -> None:
    engine = _build_engine()
    records = []
    monkeypatch.setattr(engine.decision_logger, "log", lambda record: records.append(record))
    features = _sample_features()

    engine._log_decision(
        features=features,
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890",
        summary="summary",
        strategy_output=SimpleNamespace(
            analysis_view=SimpleNamespace(action=SignalAction.BUY, confidence=0.66, reason="analysis"),
            gate_decision=SimpleNamespace(note="1H bullish"),
            entry_tier="template-qualified",
            signal_candle_source="previous_confirmed",
            entry_template=SimpleNamespace(action=SignalAction.BUY, template_name="pullback_long"),
        ),
        signal=TradeSignal(action=SignalAction.BUY, confidence=0.71, reason="final", size=0.01),
    )

    assert records[0].analysis_action == "buy"
    assert records[0].gated_action == "buy"
    assert records[0].final_strategy_action == "buy"
    assert records[0].higher_timeframe_note == "1H bullish"
    assert records[0].entry_tier == "template-qualified"
    assert records[0].signal_candle_source == "previous_confirmed"
    assert records[0].template_present is True
    assert records[0].template_name == "pullback_long"
    payload = records[0].as_dict()
    assert payload["llm_action"] == "buy"
    assert payload["strategy_action"] == "buy"
    assert payload["entry_tier"] == "template-qualified"
    assert payload["signal_candle_source"] == "previous_confirmed"
    assert payload["template_present"] is True


def test_log_decision_accepts_string_actions_for_compatibility(monkeypatch) -> None:
    engine = _build_engine()
    records = []
    monkeypatch.setattr(engine.decision_logger, "log", lambda record: records.append(record))
    features = _sample_features()

    engine._log_decision(
        features=features,
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890",
        summary="summary",
        strategy_output=SimpleNamespace(
            analysis_view=SimpleNamespace(action="buy", confidence=0.66, reason="analysis"),
            gate_decision=SimpleNamespace(note="1H bullish"),
            entry_tier="template-qualified",
            signal_candle_source="latest_confirmed",
            entry_template=SimpleNamespace(action="buy", template_name="pullback_long"),
        ),
        signal=TradeSignal(action=SignalAction.BUY, confidence=0.71, reason="final", size=0.01),
    )

    assert records[0].analysis_action == "buy"
    assert records[0].gated_action == "buy"
    assert records[0].entry_tier == "template-qualified"


def test_log_decision_tolerates_partial_analysis_view(monkeypatch) -> None:
    engine = _build_engine()
    records = []
    monkeypatch.setattr(engine.decision_logger, "log", lambda record: records.append(record))
    features = _sample_features()

    engine._log_decision(
        features=features,
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890",
        summary="summary",
        strategy_output=SimpleNamespace(
            analysis_view=SimpleNamespace(action=SignalAction.BUY),
            gate_decision=SimpleNamespace(note="1H mixed"),
            entry_tier="none",
            signal_candle_source="latest_confirmed",
            entry_template=None,
        ),
        signal=TradeSignal(action=SignalAction.HOLD, confidence=0.4, reason="final", size=0.0),
    )

    assert records[0].analysis_action == "buy"
    assert records[0].analysis_confidence == 0.0
    assert records[0].analysis_reason == ""
    assert records[0].template_present is False


def test_log_decision_tolerates_non_numeric_analysis_confidence(monkeypatch) -> None:
    engine = _build_engine()
    records = []
    monkeypatch.setattr(engine.decision_logger, "log", lambda record: records.append(record))
    features = _sample_features()

    engine._log_decision(
        features=features,
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890",
        summary="summary",
        strategy_output=SimpleNamespace(
            analysis_view=SimpleNamespace(action=SignalAction.BUY, confidence="N/A", reason="analysis"),
            gate_decision=SimpleNamespace(note="1H mixed"),
            entry_tier="none",
            signal_candle_source="latest_confirmed",
            entry_template=None,
        ),
        signal=TradeSignal(action=SignalAction.HOLD, confidence=0.4, reason="final", size=0.0),
    )

    assert records[0].analysis_confidence == 0.0


def test_log_decision_tolerates_empty_features(monkeypatch) -> None:
    engine = _build_engine()
    records = []
    monkeypatch.setattr(engine.decision_logger, "log", lambda record: records.append(record))

    engine._log_decision(
        features=pd.DataFrame(),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890",
        summary="summary",
        strategy_output=SimpleNamespace(
            analysis_view=SimpleNamespace(action=SignalAction.BUY, confidence=0.66, reason="analysis"),
            gate_decision=SimpleNamespace(note="1H mixed"),
            entry_tier="none",
            signal_candle_source="latest_confirmed",
            entry_template=None,
        ),
        signal=TradeSignal(action=SignalAction.HOLD, confidence=0.4, reason="final", size=0.0),
    )

    assert records[0].timestamp == ""
    assert records[0].close_price == 0.0


def test_log_decision_normalizes_non_finite_values(monkeypatch) -> None:
    engine = _build_engine()
    records = []
    monkeypatch.setattr(engine.decision_logger, "log", lambda record: records.append(record))
    features = pd.DataFrame([{"ts": "2026-01-01T00:00:00Z", "close": math.nan}])

    engine._log_decision(
        features=features,
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890",
        summary="summary",
        strategy_output=SimpleNamespace(
            analysis_view=SimpleNamespace(action=SignalAction.BUY, confidence=math.nan, reason="analysis"),
            gate_decision=SimpleNamespace(note="1H mixed"),
            entry_tier="none",
            signal_candle_source="latest_confirmed",
            entry_template=None,
        ),
        signal=TradeSignal(action=SignalAction.HOLD, confidence=0.4, reason="final", size=0.0),
    )

    assert records[0].analysis_confidence == 0.0
    assert records[0].close_price == 0.0


def test_strategy_step_only_generates_signal_without_risk(monkeypatch) -> None:
    engine = _build_engine()
    features = _sample_features()
    data_bundle = DataBundle(
        features=features,
        higher_features={},
        snapshot=None,
        account_snapshot={"equity": 800.0, "available": 300.0},
        risk_note="risk-note",
    )
    analysis_bundle = AnalysisBundle(
        analysis_result=MarketAnalysis(text="x", summary="s", history_hint="h"),
        analysis_text="x",
        strategy_analysis_text='{"action":"hold","confidence":0.5}',
        brain_decision=None,
        market_intel=None,
    )
    generated_output = SimpleNamespace(marker="strategy-output")

    def _fake_generate_signal(
        context,
        step_features,
        analysis_text,
        higher_features,
        llm_influence_enabled=False,
        market_analysis=None,
    ):
        assert isinstance(context, StrategyContext)
        assert context.inst_id == "ETH-USDT-SWAP"
        assert step_features is features
        assert analysis_text == '{"action":"hold","confidence":0.5}'
        assert higher_features == {}
        assert llm_influence_enabled is False
        assert market_analysis is analysis_bundle.analysis_result
        return generated_output

    def _risk_should_not_be_called(*args, **kwargs):
        raise AssertionError("risk manager should not be called in strategy step")

    monkeypatch.setattr(engine, "strategy", SimpleNamespace(generate_signal=_fake_generate_signal))
    monkeypatch.setattr(engine.risk_manager, "evaluate", _risk_should_not_be_called)

    bundle = engine._run_strategy_step(
        inst_id="ETH-USDT-SWAP",
        timeframe="15m",
        dry_run=True,
        max_position=0.02,
        higher_timeframes=("1H",),
        protection_overrides=None,
        exchange_protection_enabled=True,
        data_bundle=data_bundle,
        analysis_bundle=analysis_bundle,
    )

    assert bundle.strategy_output is generated_output


def test_build_default_protection_config_uses_upl_ratio_settings() -> None:
    settings = SimpleNamespace(
        account=SimpleNamespace(okx_td_mode=None, okx_force_pos_side=None),
        strategy=SimpleNamespace(
            balance_usage_ratio=0.5,
            default_leverage=1.0,
            default_take_profit_upl_ratio=0.2,
            default_stop_loss_upl_ratio=0.1,
        ),
        runtime=SimpleNamespace(data_staleness_seconds=180),
        intel=SimpleNamespace(
            event_gate_mode="degrade",
            event_gate_degrade_threshold=0.72,
            event_gate_block_threshold=0.9,
            event_gate_degrade_confidence_cap=0.45,
            event_gate_degrade_size_ratio=0.5,
        ),
    )
    engine = TradingEngine(
        okx_client=SimpleNamespace(),
        analyzer=SimpleNamespace(),
        strategy=SimpleNamespace(),
        settings=settings,
    )

    assert engine._default_protection_config == {
        "take_profit": {
            "mode": "percent",
            "value": 0.2,
            "trigger_type": "last",
            "order_type": "market",
        },
        "stop_loss": {
            "mode": "percent",
            "value": 0.1,
            "trigger_type": "last",
            "order_type": "market",
        },
    }


def test_build_default_protection_config_does_not_fallback_to_legacy_pct_fields() -> None:
    settings = SimpleNamespace(
        account=SimpleNamespace(okx_td_mode=None, okx_force_pos_side=None),
        strategy=SimpleNamespace(
            balance_usage_ratio=0.5,
            default_leverage=1.0,
            default_take_profit_pct=0.2,
            default_stop_loss_pct=0.1,
        ),
        runtime=SimpleNamespace(data_staleness_seconds=180),
        intel=SimpleNamespace(
            event_gate_mode="degrade",
            event_gate_degrade_threshold=0.72,
            event_gate_block_threshold=0.9,
            event_gate_degrade_confidence_cap=0.45,
            event_gate_degrade_size_ratio=0.5,
        ),
    )
    engine = TradingEngine(
        okx_client=SimpleNamespace(),
        analyzer=SimpleNamespace(),
        strategy=SimpleNamespace(),
        settings=settings,
    )

    assert engine._default_protection_config == {}


def test_strategy_step_omits_exchange_protection_when_disabled(monkeypatch) -> None:
    engine = _build_engine()
    features = _sample_features()
    data_bundle = DataBundle(
        features=features,
        higher_features={},
        snapshot={"mock": True},
        account_snapshot={"equity": 1000.0, "available": 600.0},
        risk_note=None,
    )
    analysis_bundle = AnalysisBundle(
        analysis_result=MarketAnalysis(text="analysis", summary="summary", history_hint="hint"),
        analysis_text="analysis",
        strategy_analysis_text='{"action":"buy","confidence":0.8}',
        brain_decision=None,
        market_intel=None,
    )

    def _fake_generate_signal(
        context,
        step_features,
        analysis_text,
        higher_features,
        llm_influence_enabled=False,
        market_analysis=None,
    ):
        assert context.protection is None
        return SimpleNamespace(marker="strategy-output")

    monkeypatch.setattr(engine, "strategy", SimpleNamespace(generate_signal=_fake_generate_signal))

    bundle = engine._run_strategy_step(
        inst_id="ETH-USDT-SWAP",
        timeframe="15m",
        dry_run=False,
        max_position=0.02,
        higher_timeframes=("1H",),
        protection_overrides={"take_profit": {"mode": "percent", "value": 0.06}},
        exchange_protection_enabled=False,
        data_bundle=data_bundle,
        analysis_bundle=analysis_bundle,
    )

    assert bundle.strategy_output.marker == "strategy-output"


def test_run_once_structured_logs_with_trace_id(monkeypatch) -> None:
    from core.engine import trading as trading_module

    engine = _build_engine()
    features = _sample_features()
    risk_signal = TradeSignal(
        action=SignalAction.SELL,
        confidence=0.61,
        reason="risk-passed",
        size=0.02,
    )
    data_step_output = DataBundle(
        features=features,
        higher_features={"15m": features},
        snapshot={"mock": True},
        account_snapshot={"equity": 1200.0, "available": 700.0},
        risk_note=None,
    )
    analysis_step_output = AnalysisBundle(
        analysis_result=MarketAnalysis(text="a", summary="s", history_hint="h"),
        analysis_text="a",
        strategy_analysis_text='{"action":"sell","confidence":0.6}',
        brain_decision=None,
        market_intel=None,
    )
    strategy_signal = TradeSignal(
        action=SignalAction.SELL,
        confidence=0.64,
        reason="strategy",
        size=0.02,
    )
    strategy_step_output = StrategyBundle(
        context=StrategyContext(inst_id="BTC-USDT-SWAP", timeframe="5m", max_position=0.01),
        strategy_output=SimpleNamespace(trade_signal=strategy_signal, analysis_view=SimpleNamespace(action=SignalAction.SELL, confidence=0.64, reason="x")),
    )
    risk_step_output = RiskBundle(
        account_state=AccountState(equity=1200.0, available=700.0),
        risk_assessment=RiskAssessment(
            trade_signal=risk_signal,
            notes=(),
            blocked=False,
            account_state=AccountState(equity=1200.0, available=700.0),
        ),
        signal=risk_signal,
    )
    execution_step_output = ExecutionBundle(
        plan=ExecutionPlan(
            inst_id="BTC-USDT-SWAP",
            action=SignalAction.SELL,
            td_mode="cross",
            pos_side="short",
            order_type="market",
            size=0.02,
            price=None,
            est_slippage=0.0,
        ),
        report=None,
        order=None,
    )

    monkeypatch.setattr(engine, "_run_data_step", lambda **_: data_step_output)
    monkeypatch.setattr(engine, "_run_analysis_step", lambda **_: analysis_step_output)
    monkeypatch.setattr(engine, "_run_strategy_step", lambda **_: strategy_step_output)
    monkeypatch.setattr(engine, "_run_risk_step", lambda **_: risk_step_output)
    monkeypatch.setattr(engine, "_run_execution_step", lambda **_: execution_step_output)
    monkeypatch.setattr(engine, "_log_decision", lambda **_: None)

    records = []
    sink_id = trading_module.logger.add(lambda m: records.append(m.record), level="INFO")
    try:
        result = engine.run_once(inst_id="BTC-USDT-SWAP", timeframe="5m", dry_run=True)
    finally:
        trading_module.logger.remove(sink_id)

    trace_id = result["trace_id"]
    structured = [r for r in records if str(r["message"]).startswith("event=")]
    assert structured
    for rec in structured:
        assert rec["extra"].get("trace_id") == trace_id
        assert rec["extra"].get("inst_id") == "BTC-USDT-SWAP"
        assert rec["extra"].get("timeframe") == "5m"

    messages = [r["message"] for r in structured]
    assert any("event=analysis_done action=analysis blocked=False error_code=" in msg for msg in messages)
    assert any("event=signal_done action=sell blocked=False error_code=" in msg for msg in messages)
    assert any("event=risk_done action=sell blocked=False error_code=" in msg for msg in messages)
    assert any("event=execution_done action=sell blocked=False error_code=" in msg for msg in messages)


def test_execution_step_blocks_when_data_stale(monkeypatch) -> None:
    engine = _build_engine()
    stale_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=40)
    features = pd.DataFrame([{"ts": stale_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.01,
        price=None,
        est_slippage=0.0,
    )

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)

    def _should_not_execute(_plan):
        raise AssertionError("stale data should block execution")

    monkeypatch.setattr(engine.execution_engine, "execute", _should_not_execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
    )

    assert bundle.plan.blocked is True
    assert bundle.report is None
    assert "数据新鲜度闸门" in (bundle.plan.block_reason or "")


def test_execution_step_passes_runtime_leverage_to_execution_engine(monkeypatch) -> None:
    engine = _build_engine()
    engine.leverage = 7.0
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.01,
        price=None,
        est_slippage=0.0,
    )
    captured: dict[str, object] = {}

    def _build_plan(**kwargs):
        captured.update(kwargs)
        return built_plan

    monkeypatch.setattr(engine.execution_engine, "build_plan", _build_plan)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=True,
        signal=signal,
        features=features,
    )

    assert bundle.plan is built_plan
    assert captured["leverage"] == 7.0


def test_execution_step_allows_fresh_data(monkeypatch) -> None:
    engine = _build_engine()
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.01,
        price=None,
        est_slippage=0.0,
    )

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    called = {"ok": False}

    def _execute(_plan):
        called["ok"] = True
        return SimpleNamespace(success=True, response={"ordId": "1"}, code=None, error=None)

    monkeypatch.setattr(engine.execution_engine, "execute", _execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
    )

    assert called["ok"] is True
    assert bundle.plan.blocked is False


def test_execution_step_blocks_when_live_pending_order_exists(monkeypatch) -> None:
    engine = _build_engine()
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="limit",
        size=0.01,
        price=99.5,
        est_slippage=0.001,
    )

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    monkeypatch.setattr(engine.execution_engine, "has_live_pending_order", lambda inst_id: inst_id == "BTC-USDT-SWAP")

    def _should_not_execute(_plan):
        raise AssertionError("existing pending order should block duplicate execution")

    monkeypatch.setattr(engine.execution_engine, "execute", _should_not_execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
    )

    assert bundle.plan.blocked is True
    assert bundle.report is None
    assert "未成交委托" in (bundle.plan.block_reason or "")


def test_execution_step_cancels_stale_pending_order_and_blocks_current_cycle(monkeypatch) -> None:
    engine = _build_engine()
    engine.runtime_settings.execution_pending_order_ttl_minutes = 60
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="limit",
        size=0.01,
        price=99.5,
        est_slippage=0.001,
    )
    stale_entry = {
        "instId": "BTC-USDT-SWAP",
        "ordId": "stale-ord-1",
        "clOrdId": "stale-cl-1",
        "state": "live",
        "ordType": "limit",
        "accFillSz": "0",
        "reduceOnly": "false",
        "cTime": "1710000000000",
    }
    cancelled = []

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    monkeypatch.setattr(engine.execution_engine, "list_live_pending_orders", lambda inst_id: [stale_entry])
    monkeypatch.setattr(
        engine.execution_engine,
        "is_pending_order_stale",
        lambda entry, ttl_minutes: ttl_minutes == 60,
    )
    monkeypatch.setattr(engine.execution_engine, "has_live_pending_order", lambda inst_id: False)

    okx = SimpleNamespace(
        cancel_order=lambda **kwargs: cancelled.append(kwargs) or {"code": "0", "data": [{"sCode": "0", "sMsg": ""}]}
    )
    engine.okx = okx
    engine.execution_engine.okx = okx

    def _should_not_execute(_plan):
        raise AssertionError("stale pending cancel should block the current cycle")

    monkeypatch.setattr(engine.execution_engine, "execute", _should_not_execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
    )

    assert cancelled == [
        {
            "inst_id": "BTC-USDT-SWAP",
            "ord_id": "stale-ord-1",
            "cl_ord_id": "stale-cl-1",
        }
    ]
    assert bundle.plan.blocked is True
    assert bundle.report is None
    assert bundle.plan.block_reason == "存在未成交委托：BTC-USDT-SWAP 已撤销超时挂单，下一轮再评估。"


def test_execution_step_blocks_when_stale_pending_cancel_fails(monkeypatch) -> None:
    engine = _build_engine()
    engine.runtime_settings.execution_pending_order_ttl_minutes = 60
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="limit",
        size=0.01,
        price=99.5,
        est_slippage=0.001,
    )
    stale_entry = {
        "instId": "BTC-USDT-SWAP",
        "ordId": "stale-ord-1",
        "clOrdId": "stale-cl-1",
        "state": "live",
        "ordType": "limit",
        "accFillSz": "0",
        "reduceOnly": "false",
        "cTime": "1710000000000",
    }

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    monkeypatch.setattr(engine.execution_engine, "list_live_pending_orders", lambda inst_id: [stale_entry])
    monkeypatch.setattr(
        engine.execution_engine,
        "is_pending_order_stale",
        lambda entry, ttl_minutes: ttl_minutes == 60,
    )
    monkeypatch.setattr(engine.execution_engine, "has_live_pending_order", lambda inst_id: False)

    okx = SimpleNamespace(
        cancel_order=lambda **kwargs: {
            "error": {"code": "54000", "message": "cancel failed"},
            "data": [{"sCode": "54000", "sMsg": "reject"}],
        }
    )
    engine.okx = okx
    engine.execution_engine.okx = okx

    def _should_not_execute(_plan):
        raise AssertionError("failed stale pending cancel should still block the current cycle")

    monkeypatch.setattr(engine.execution_engine, "execute", _should_not_execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
    )

    assert bundle.plan.blocked is True
    assert bundle.report is None
    assert bundle.plan.block_reason == "存在未成交委托：BTC-USDT-SWAP 超时挂单撤单失败，当前轮跳过。"


def test_execution_step_blocks_when_same_direction_position_exists(monkeypatch) -> None:
    engine = _build_engine()
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.01)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.01,
        price=None,
        est_slippage=0.0,
    )

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    engine.execution_engine.okx = SimpleNamespace(
        get_positions=lambda inst_type="SWAP": {
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "posSide": "net",
                    "pos": "1",
                }
            ]
        }
    )

    def _should_not_execute(_plan):
        raise AssertionError("same-direction position should block duplicate execution")

    monkeypatch.setattr(engine.execution_engine, "execute", _should_not_execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
    )

    assert bundle.plan.blocked is True
    assert bundle.report is None
    assert "同向持仓" in (bundle.plan.block_reason or "")


def test_execution_step_allows_same_direction_scale_in_when_enabled(monkeypatch) -> None:
    engine = _build_engine()
    engine.runtime_settings.execution_allow_same_direction_scale_in = True
    engine.runtime_settings.execution_same_direction_scale_in_multiplier = 3.0
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.03)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.03,
        price=None,
        est_slippage=0.0,
    )
    captured = {"size": None}

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    monkeypatch.setattr(
        engine.execution_engine,
        "same_direction_position_size",
        lambda inst_id, action, latest_price=None: 0.025,
    )
    monkeypatch.setattr(engine.execution_engine, "get_min_underlying_size", lambda inst_id, latest_price: 0.001)

    def _execute(plan):
        captured["size"] = plan.size
        return SimpleNamespace(success=True, response={"ordId": "1"}, code=None, error=None)

    monkeypatch.setattr(engine.execution_engine, "execute", _execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
        max_position=0.02,
    )

    assert bundle.plan.blocked is False
    assert captured["size"] == 0.03


def test_execution_step_blocks_when_same_direction_scale_in_limit_reached(monkeypatch) -> None:
    engine = _build_engine()
    engine.runtime_settings.execution_allow_same_direction_scale_in = True
    engine.runtime_settings.execution_same_direction_scale_in_multiplier = 3.0
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.03)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.03,
        price=None,
        est_slippage=0.0,
    )

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    monkeypatch.setattr(
        engine.execution_engine,
        "same_direction_position_size",
        lambda inst_id, action, latest_price=None: 0.06,
    )
    monkeypatch.setattr(engine.execution_engine, "get_min_underlying_size", lambda inst_id, latest_price: 0.001)

    def _should_not_execute(_plan):
        raise AssertionError("scale-in limit should block further same-direction orders")

    monkeypatch.setattr(engine.execution_engine, "execute", _should_not_execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
        max_position=0.02,
    )

    assert bundle.plan.blocked is True
    assert bundle.report is None
    assert "加仓上限" in (bundle.plan.block_reason or "")


def test_execution_step_caps_same_direction_scale_in_to_remaining_capacity(monkeypatch) -> None:
    engine = _build_engine()
    engine.runtime_settings.execution_allow_same_direction_scale_in = True
    engine.runtime_settings.execution_same_direction_scale_in_multiplier = 3.0
    fresh_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=30)
    features = pd.DataFrame([{"ts": fresh_ts, "close": 100.0, "atr": 1.0}])
    signal = TradeSignal(action=SignalAction.BUY, confidence=0.7, reason="x", size=0.03)

    built_plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.03,
        price=None,
        est_slippage=0.0,
    )
    captured = {"size": None}

    monkeypatch.setattr(engine.execution_engine, "build_plan", lambda **kwargs: built_plan)
    monkeypatch.setattr(
        engine.execution_engine,
        "same_direction_position_size",
        lambda inst_id, action, latest_price=None: 0.05,
    )
    monkeypatch.setattr(engine.execution_engine, "get_min_underlying_size", lambda inst_id, latest_price: 0.001)

    def _execute(plan):
        captured["size"] = plan.size
        return SimpleNamespace(success=True, response={"ordId": "1"}, code=None, error=None)

    monkeypatch.setattr(engine.execution_engine, "execute", _execute)

    bundle = engine._run_execution_step(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        trace_id="trace1234567890a",
        dry_run=False,
        signal=signal,
        features=features,
        max_position=0.02,
    )

    assert bundle.plan.blocked is False
    assert captured["size"] == pytest.approx(0.01)
    assert any("加仓剩余额度" in note for note in bundle.plan.notes)


def test_feature_min_samples_gate() -> None:
    engine = _build_engine()
    engine.feature_min_samples = 5
    features = pd.DataFrame(
        [
            {"ts": "2026-01-01T00:00:00Z", "close": 100.0, "atr": 1.0},
            {"ts": "2026-01-01T00:05:00Z", "close": 100.1, "atr": 1.0},
            {"ts": "2026-01-01T00:10:00Z", "close": 100.2, "atr": 1.0},
        ]
    )

    with pytest.raises(ValueError):
        engine._ensure_feature_samples(features, inst_id="BTC-USDT-SWAP", timeframe="5m")
