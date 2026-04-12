"""Notification center tests."""

from __future__ import annotations

from core.utils.notifications import NotificationCenter, NotificationEvent


class _Transport:
    def __init__(self) -> None:
        self.messages = []

    def send(self, message: str, parse_mode=None) -> None:
        self.messages.append((message, parse_mode))


def test_notification_center_filters_events_by_level() -> None:
    transport = _Transport()
    center = NotificationCenter(transport=transport, level="critical", cooldown_seconds=60.0)

    center.publish(NotificationEvent(kind="order_submitted", inst_id="BTC-USDT-SWAP", message="ok"))
    center.publish(NotificationEvent(kind="trade_blocked", inst_id="BTC-USDT-SWAP", message="blocked"))
    center.publish(NotificationEvent(kind="runtime_error", inst_id="BTC-USDT-SWAP", message="err"))

    assert [item[0] for item in transport.messages] == ["blocked", "err"]


def test_notification_center_applies_cooldown_per_event_and_inst() -> None:
    transport = _Transport()
    center = NotificationCenter(transport=transport, level="orders", cooldown_seconds=60.0)

    center.publish(NotificationEvent(kind="trade_blocked", inst_id="BTC-USDT-SWAP", message="blocked-1"))
    center.publish(NotificationEvent(kind="trade_blocked", inst_id="BTC-USDT-SWAP", message="blocked-2"))
    center.publish(NotificationEvent(kind="trade_blocked", inst_id="ETH-USDT-SWAP", message="blocked-3"))

    assert [item[0] for item in transport.messages] == ["blocked-1", "blocked-3"]
