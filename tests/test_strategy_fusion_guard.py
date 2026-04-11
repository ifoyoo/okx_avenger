"""LLM 影响上限融合测试。"""

from __future__ import annotations

from core.models import SignalAction
from core.strategy.fusion import (
    AnalysisView,
    ConflictArbitrationConfig,
    LLMInfluenceGuard,
    SignalFusionEngine,
)
from core.strategy.signals import ObjectiveSignal


def _signals(indicator_action: SignalAction, indicator_conf: float = 0.6):
    return (
        ObjectiveSignal("indicator", indicator_action, indicator_conf, "indicator"),
    )


def _plugin_signal(name: str, action: SignalAction, confidence: float):
    return ObjectiveSignal(name, action, confidence, f"{name}-{action.value}")


def test_llm_reverse_is_blocked_to_hold() -> None:
    engine = SignalFusionEngine()
    analysis = AnalysisView(action=SignalAction.SELL, confidence=0.95, reason="llm")
    guard = LLMInfluenceGuard(
        enabled=True,
        max_confidence_delta=0.15,
        allow_direction_reverse=False,
        allow_hold_to_direction=False,
    )

    fused = engine.fuse(_signals(SignalAction.BUY, 0.62), analysis, llm_guard=guard)

    assert fused.action == SignalAction.HOLD
    assert fused.confidence <= 0.62
    assert any("LLM 影响上限" in note for note in fused.notes)


def test_llm_hold_promotion_blocked() -> None:
    engine = SignalFusionEngine()
    analysis = AnalysisView(action=SignalAction.BUY, confidence=0.9, reason="llm")
    guard = LLMInfluenceGuard(
        enabled=True,
        max_confidence_delta=0.2,
        allow_direction_reverse=False,
        allow_hold_to_direction=False,
    )

    fused = engine.fuse(_signals(SignalAction.HOLD, 0.4), analysis, llm_guard=guard)

    assert fused.action == SignalAction.HOLD
    assert any("HOLD" in note for note in fused.notes)


def test_llm_confidence_is_capped_by_delta() -> None:
    engine = SignalFusionEngine()
    analysis = AnalysisView(action=SignalAction.BUY, confidence=0.95, reason="llm")
    guard = LLMInfluenceGuard(
        enabled=True,
        max_confidence_delta=0.08,
        allow_direction_reverse=False,
        allow_hold_to_direction=False,
    )

    fused = engine.fuse(_signals(SignalAction.BUY, 0.55), analysis, llm_guard=guard)

    assert fused.action == SignalAction.BUY
    assert fused.confidence <= 0.63 + 1e-9


def test_conflict_arbitration_boosts_same_direction() -> None:
    engine = SignalFusionEngine()
    analysis = AnalysisView(action=SignalAction.BUY, confidence=0.55, reason="det")
    signals = (
        ObjectiveSignal("indicator", SignalAction.BUY, 0.56, "indicator"),
        _plugin_signal("ma_golden_cross", SignalAction.BUY, 0.72),
        _plugin_signal("volume_breakout", SignalAction.BUY, 0.66),
    )
    disabled = engine.fuse(
        signals,
        analysis,
        arbitration_config=ConflictArbitrationConfig(enabled=False),
    )
    enabled = engine.fuse(
        signals,
        analysis,
        arbitration_config=ConflictArbitrationConfig(enabled=True, same_side_boost=0.12),
    )

    assert enabled.action == SignalAction.BUY
    assert enabled.confidence > disabled.confidence
    assert any(note.startswith("[arb]") for note in enabled.notes)


def test_conflict_arbitration_can_degrade_to_hold() -> None:
    engine = SignalFusionEngine()
    analysis = AnalysisView(action=SignalAction.BUY, confidence=0.68, reason="det")
    signals = (
        ObjectiveSignal("indicator", SignalAction.BUY, 0.72, "indicator"),
        _plugin_signal("volume_pressure", SignalAction.SELL, 0.92),
        _plugin_signal("box_oscillation", SignalAction.SELL, 0.87),
    )
    fused = engine.fuse(
        signals,
        analysis,
        arbitration_config=ConflictArbitrationConfig(
            enabled=True,
            opposite_side_penalty=0.2,
            strong_conflict_ratio=0.58,
            hold_confidence_cap=0.3,
            min_directional_signals=2,
        ),
    )

    assert fused.action == SignalAction.HOLD
    assert fused.confidence <= 0.3
    assert any("decision=hold" in note for note in fused.notes)
