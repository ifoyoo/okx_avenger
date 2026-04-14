"""交易编排 pipeline 拆分测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

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

    def _fake_execution_step(*, inst_id, timeframe, trace_id, dry_run, signal, features):
        events.append("execution")
        assert inst_id == "BTC-USDT-SWAP"
        assert timeframe == "5m"
        assert isinstance(trace_id, str)
        assert len(trace_id) == 16
        assert dry_run is True
        assert signal is risk_signal
        assert features is data_step_output.features
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
    assert result["execution"]["plan"] is execution_step_output.plan
    assert result["order"] == {"ordId": "demo"}


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
