"""Utilities for building stop-loss / take-profit settings."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import ProtectionRule, ProtectionSettings


def build_protection_settings(overrides: Optional[Dict[str, Any]] = None) -> ProtectionSettings:
    data = overrides or {}
    tp_rule = _build_rule(data.get("take_profit"))
    sl_rule = _build_rule(data.get("stop_loss"))
    return ProtectionSettings(take_profit=tp_rule, stop_loss=sl_rule)


def _build_rule(override: Optional[Dict[str, Any]]) -> ProtectionRule:
    data = override or {}
    mode = str(data.get("mode", "disabled")).strip().lower()
    trigger = str(data.get("trigger_type", "last")).strip().lower() or "last"
    order_type = str(data.get("order_type", "market")).strip().lower() or "market"
    raw_value = data.get("value", 0)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = 0.0
    return ProtectionRule(mode=mode, value=value, trigger_type=trigger, order_type=order_type)
