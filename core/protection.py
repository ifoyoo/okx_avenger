"""Utilities for building and resolving stop-loss / take-profit settings."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.models import (
    ProtectionRule,
    ProtectionSettings,
    ProtectionTarget,
    ResolvedTradeProtection,
    SignalAction,
    TradeProtection,
)


def build_protection_settings(overrides: Optional[Dict[str, Any]] = None) -> ProtectionSettings:
    data = overrides or {}
    tp_rule = _build_rule(data.get("take_profit"))
    sl_rule = _build_rule(data.get("stop_loss"))
    return ProtectionSettings(take_profit=tp_rule, stop_loss=sl_rule)


def _build_rule(override: Optional[Dict[str, Any]]) -> ProtectionRule:
    data = override or {}
    mode = ProtectionRule.normalize_mode(data.get("mode", "disabled"))
    trigger = str(data.get("trigger_type", "last")).strip().lower() or "last"
    order_type = str(data.get("order_type", "market")).strip().lower() or "market"
    raw_value = data.get("value", 0)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = 0.0
    return ProtectionRule(mode=mode, value=value, trigger_type=trigger, order_type=order_type)


def resolve_trade_protection(
    *,
    protection: Optional[TradeProtection],
    action: SignalAction,
    entry_price: float,
    atr: float,
) -> Optional[ResolvedTradeProtection]:
    if protection is None or action == SignalAction.HOLD or entry_price <= 0:
        return None
    stop_loss = _resolve_target(
        rule=protection.stop_loss,
        action=action,
        entry_price=entry_price,
        atr=atr,
        kind="sl",
        stop_loss=None,
    )
    take_profit = _resolve_target(
        rule=protection.take_profit,
        action=action,
        entry_price=entry_price,
        atr=atr,
        kind="tp",
        stop_loss=stop_loss,
    )
    if not take_profit and not stop_loss:
        return None
    return ResolvedTradeProtection(take_profit=take_profit, stop_loss=stop_loss)


def _resolve_target(
    *,
    rule: Optional[ProtectionRule],
    action: SignalAction,
    entry_price: float,
    atr: float,
    kind: str,
    stop_loss: Optional[ProtectionTarget],
) -> Optional[ProtectionTarget]:
    if not rule or not rule.is_active():
        return None
    mode = rule.normalized_mode()
    try:
        value = abs(float(rule.value or 0.0))
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return None

    direction = 1 if action == SignalAction.BUY else -1
    sign = direction if kind == "tp" else -direction
    trigger_ratio: Optional[float] = None
    trigger_px: Optional[float] = None
    order_type = (rule.order_type or "market").lower()
    trigger_type = (rule.trigger_type or "last").lower() or "last"
    order_kind = "limit" if order_type == "limit" else "condition"

    if mode == "percent":
        trigger_ratio = value * sign
        trigger_px = entry_price * (1 + trigger_ratio)
        order_type = "market"
        order_kind = "condition"
    elif mode == "atr":
        if atr <= 0:
            return None
        trigger_px = entry_price + sign * atr * value
    elif mode == "price":
        trigger_px = value
    elif mode == "rr":
        if kind != "tp" or not stop_loss or not stop_loss.has_price():
            return None
        risk_distance = abs(entry_price - float(stop_loss.trigger_px or 0.0))
        if risk_distance <= 0:
            return None
        trigger_px = entry_price + direction * risk_distance * value
    else:
        return None

    if trigger_px is not None and trigger_px <= 0:
        return None
    order_px = trigger_px if (trigger_px and order_type == "limit") else None
    return ProtectionTarget(
        trigger_ratio=trigger_ratio,
        trigger_px=trigger_px,
        order_px=order_px,
        trigger_type=trigger_type,
        order_type=order_type,
        order_kind=order_kind,
        mode=mode,
    )
