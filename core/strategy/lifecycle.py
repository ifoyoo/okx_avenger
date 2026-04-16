from __future__ import annotations

from dataclasses import dataclass

from core.models import SignalAction

RISK_DISTANCE_MULTIPLIER = 1.1
TP2_MULTIPLIER = 2.0
SCALE_IN_TRIGGER_MULTIPLIER = 0.8


@dataclass(frozen=True)
class LifecyclePlan:
    action: SignalAction
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    scale_in_trigger_price: float
    scale_in_size_ratio: float


@dataclass(frozen=True)
class LifecycleStage:
    stop_price: float
    tp1_hit: bool
    tp2_hit: bool
    scale_in_done: bool


def build_lifecycle_plan(
    action: SignalAction,
    entry_price: float,
    atr: float,
    scale_in_ratio: float = 0.35,
) -> LifecyclePlan:
    direction = _direction_for_action(action)
    if atr <= 0:
        raise ValueError("atr must be positive")
    risk_distance = atr * RISK_DISTANCE_MULTIPLIER

    stop_price = entry_price - direction * risk_distance
    tp1_price = entry_price + direction * risk_distance
    tp2_price = entry_price + direction * risk_distance * TP2_MULTIPLIER
    scale_in_trigger_price = entry_price + direction * risk_distance * SCALE_IN_TRIGGER_MULTIPLIER

    return LifecyclePlan(
        action,
        entry_price,
        stop_price,
        tp1_price,
        tp2_price,
        scale_in_trigger_price,
        scale_in_ratio,
    )


def evaluate_lifecycle_stage(
    plan: LifecyclePlan,
    mark_price: float,
    tp1_hit: bool,
    tp2_hit: bool,
    scale_in_done: bool,
) -> LifecycleStage:
    direction = _direction_for_action(plan.action)

    next_tp2_hit = tp2_hit or direction * (mark_price - plan.tp2_price) >= 0
    next_tp1_hit = tp1_hit or next_tp2_hit or direction * (mark_price - plan.tp1_price) >= 0

    stop_price = plan.stop_price
    if next_tp1_hit:
        stop_price = plan.entry_price

    return LifecycleStage(
        stop_price=stop_price,
        tp1_hit=next_tp1_hit,
        tp2_hit=next_tp2_hit,
        scale_in_done=scale_in_done,
    )


def _direction_for_action(action: SignalAction) -> int:
    if action == SignalAction.BUY:
        return 1
    if action == SignalAction.SELL:
        return -1
    raise ValueError("action must be directional")
