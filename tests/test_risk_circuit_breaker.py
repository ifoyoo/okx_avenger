"""RiskManager 硬风控熔断测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from core.engine.risk import AccountState, RiskManager
from core.models import SignalAction, TradeSignal


def _features() -> pd.DataFrame:
    rows = []
    for idx in range(12):
        close = 100.0 + idx * 0.1
        volume = 1000.0 + idx * 10.0
        rows.append(
            {
                "close": close,
                "atr": 1.0,
                "volume": volume,
                "volume_usd": volume * close,
            }
        )
    return pd.DataFrame(rows)


def _strategy_output() -> SimpleNamespace:
    return SimpleNamespace(
        trade_signal=TradeSignal(
            action=SignalAction.BUY,
            confidence=0.8,
            reason="raw-signal",
            size=0.01,
        ),
        analysis_view=SimpleNamespace(risk=""),
        objective_signals=(),
    )


def test_daily_loss_circuit_blocks_and_persists(tmp_path) -> None:
    state_path = tmp_path / "risk_state.json"
    manager = RiskManager(
        min_available_ratio=0.0,
        daily_loss_limit=50.0,
        consecutive_loss_limit=0,
        state_path=state_path,
    )
    account_state = AccountState(equity=1000.0, available=900.0)

    assessment = manager.evaluate(
        account_state=account_state,
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats={"total_pnl": -80.0, "consecutive_losses": 0},
        perf_stats=None,
    )

    assert assessment.blocked is True
    assert assessment.trade_signal.action == SignalAction.HOLD
    assert "日内亏损" in "；".join(assessment.notes)
    assert state_path.exists()

    manager_reloaded = RiskManager(
        min_available_ratio=0.0,
        daily_loss_limit=50.0,
        consecutive_loss_limit=0,
        state_path=state_path,
    )
    assessment_reloaded = manager_reloaded.evaluate(
        account_state=account_state,
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats={"total_pnl": -1.0, "consecutive_losses": 0},
        perf_stats=None,
    )
    assert assessment_reloaded.blocked is True
    assert assessment_reloaded.trade_signal.action == SignalAction.HOLD


def test_consecutive_loss_circuit_recovers_after_cooldown(tmp_path) -> None:
    state_path = tmp_path / "risk_state.json"
    manager = RiskManager(
        min_available_ratio=0.0,
        daily_loss_limit=0.0,
        consecutive_loss_limit=3,
        consecutive_cooldown_minutes=10,
        state_path=state_path,
    )
    account_state = AccountState(equity=1200.0, available=800.0)
    t0 = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)

    manager._utcnow = lambda: t0  # type: ignore[method-assign]
    blocked_assessment = manager.evaluate(
        account_state=account_state,
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats={"total_pnl": -20.0, "consecutive_losses": 3},
        perf_stats=None,
    )
    assert blocked_assessment.blocked is True
    assert "连续亏损" in "；".join(blocked_assessment.notes)

    manager._utcnow = lambda: t0 + timedelta(minutes=5)  # type: ignore[method-assign]
    still_blocked = manager.evaluate(
        account_state=account_state,
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats={"total_pnl": -10.0, "consecutive_losses": 0},
        perf_stats=None,
    )
    assert still_blocked.blocked is True

    manager._utcnow = lambda: t0 + timedelta(minutes=11)  # type: ignore[method-assign]
    recovered = manager.evaluate(
        account_state=account_state,
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats={"total_pnl": 5.0, "consecutive_losses": 0},
        perf_stats=None,
    )
    assert recovered.blocked is False
    assert recovered.trade_signal.action == SignalAction.BUY


def test_intel_event_gate_degrade_signal(tmp_path) -> None:
    state_path = tmp_path / "risk_state.json"
    manager = RiskManager(
        min_available_ratio=0.0,
        daily_loss_limit=0.0,
        consecutive_loss_limit=0,
        state_path=state_path,
        intel_gate_mode="degrade",
        intel_degrade_threshold=0.7,
        intel_block_threshold=0.95,
        intel_degrade_confidence_cap=0.4,
        intel_degrade_size_ratio=0.25,
    )
    assessment = manager.evaluate(
        account_state=AccountState(equity=1200.0, available=900.0),
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats=None,
        perf_stats=None,
        market_intel={
            "event_tags": {"security": 0.8, "macro": 0.6},
            "event_risk_score": 0.8,
        },
    )

    assert assessment.blocked is False
    assert assessment.trade_signal.action == SignalAction.BUY
    assert assessment.trade_signal.confidence <= 0.4
    assert abs(assessment.trade_signal.size - 0.0025) < 1e-12
    assert "情报标签闸门" in "；".join(assessment.notes)


def test_intel_event_gate_block_signal(tmp_path) -> None:
    state_path = tmp_path / "risk_state.json"
    manager = RiskManager(
        min_available_ratio=0.0,
        daily_loss_limit=0.0,
        consecutive_loss_limit=0,
        state_path=state_path,
        intel_gate_mode="block",
        intel_degrade_threshold=0.7,
        intel_block_threshold=0.9,
    )
    assessment = manager.evaluate(
        account_state=AccountState(equity=1200.0, available=900.0),
        features=_features(),
        higher_features=None,
        strategy_output=_strategy_output(),
        daily_stats=None,
        perf_stats=None,
        market_intel={
            "event_tags": {"regulation": 0.92},
            "event_risk_score": 0.92,
        },
    )

    assert assessment.blocked is True
    assert assessment.trade_signal.action == SignalAction.HOLD
    assert assessment.trade_signal.size == 0.0
    assert "情报标签闸门" in "；".join(assessment.notes)
