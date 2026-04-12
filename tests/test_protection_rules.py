"""Protection rule normalization and resolution tests."""

from __future__ import annotations

from core.models import ProtectionRule, SignalAction, TradeProtection
from core.protection import build_protection_settings, resolve_trade_protection


def test_build_protection_settings_normalizes_percent_alias() -> None:
    settings = build_protection_settings(
        {
            "take_profit": {"mode": "ratio", "value": 0.03},
            "stop_loss": {"mode": "pct", "value": 0.01},
        }
    )

    assert settings.take_profit.mode == "percent"
    assert settings.stop_loss.mode == "percent"


def test_resolve_trade_protection_supports_rr_take_profit() -> None:
    protection = TradeProtection(
        take_profit=ProtectionRule(mode="rr", value=2.0),
        stop_loss=ProtectionRule(mode="ratio", value=0.01),
    )

    resolved = resolve_trade_protection(
        protection=protection,
        action=SignalAction.BUY,
        entry_price=100.0,
        atr=5.0,
    )

    assert resolved is not None
    assert resolved.stop_loss is not None
    assert resolved.take_profit is not None
    assert resolved.stop_loss.trigger_ratio == -0.01
    assert resolved.stop_loss.trigger_px == 99.0
    assert resolved.take_profit.trigger_px == 102.0
    assert resolved.take_profit.trigger_ratio is None


def test_resolve_trade_protection_drops_rr_without_stop_loss() -> None:
    protection = TradeProtection(
        take_profit=ProtectionRule(mode="rr", value=2.0),
        stop_loss=None,
    )

    resolved = resolve_trade_protection(
        protection=protection,
        action=SignalAction.BUY,
        entry_price=100.0,
        atr=5.0,
    )

    assert resolved is None or resolved.take_profit is None
