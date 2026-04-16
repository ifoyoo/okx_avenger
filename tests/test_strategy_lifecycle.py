import pytest

from core.models import SignalAction
from core.strategy.lifecycle import build_lifecycle_plan, evaluate_lifecycle_stage


def test_build_lifecycle_plan_sets_stop_tp_targets_and_scale_in_once() -> None:
    plan = build_lifecycle_plan(
        action=SignalAction.BUY,
        entry_price=100.0,
        atr=2.0,
        scale_in_ratio=0.35,
    )

    assert round(plan.stop_price, 2) == 97.8
    assert round(plan.tp1_price, 2) == 102.2
    assert round(plan.tp2_price, 2) == 104.4
    assert round(plan.scale_in_trigger_price, 2) == 101.76
    assert plan.scale_in_size_ratio == 0.35


def test_evaluate_lifecycle_stage_moves_to_break_even_after_tp1() -> None:
    plan = build_lifecycle_plan(
        action=SignalAction.BUY,
        entry_price=100.0,
        atr=2.0,
        scale_in_ratio=0.35,
    )

    stage = evaluate_lifecycle_stage(
        plan=plan,
        mark_price=102.3,
        tp1_hit=False,
        tp2_hit=False,
        scale_in_done=False,
    )

    assert stage.tp1_hit is True
    assert stage.stop_price == 100.0


def test_lifecycle_helpers_accept_positional_arguments() -> None:
    plan = build_lifecycle_plan(SignalAction.SELL, 100.0, 2.0, 0.35)

    stage = evaluate_lifecycle_stage(plan, 97.7, False, False, False)

    assert stage.tp1_hit is True


def test_build_lifecycle_plan_sets_short_targets_below_entry() -> None:
    plan = build_lifecycle_plan(SignalAction.SELL, 100.0, 2.0, 0.35)

    assert round(plan.stop_price, 2) == 102.2
    assert round(plan.tp1_price, 2) == 97.8
    assert round(plan.tp2_price, 2) == 95.6
    assert round(plan.scale_in_trigger_price, 2) == 98.24


def test_evaluate_lifecycle_stage_marks_tp2_and_preserves_scale_in_flag() -> None:
    plan = build_lifecycle_plan(SignalAction.SELL, 100.0, 2.0, 0.35)

    stage = evaluate_lifecycle_stage(plan, 95.5, True, False, True)

    assert stage.tp1_hit is True
    assert stage.tp2_hit is True
    assert stage.scale_in_done is True
    assert stage.stop_price == 100.0


def test_evaluate_lifecycle_stage_keeps_tp1_when_tp2_is_already_hit() -> None:
    plan = build_lifecycle_plan(SignalAction.BUY, 100.0, 2.0, 0.35)

    stage = evaluate_lifecycle_stage(plan, 100.5, False, True, False)

    assert stage.tp1_hit is True
    assert stage.tp2_hit is True
    assert stage.stop_price == 100.0


def test_build_lifecycle_plan_rejects_hold_action() -> None:
    with pytest.raises(ValueError, match="directional"):
        build_lifecycle_plan(SignalAction.HOLD, 100.0, 2.0, 0.35)


def test_build_lifecycle_plan_rejects_non_positive_atr() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_lifecycle_plan(SignalAction.BUY, 100.0, 0.0, 0.35)
