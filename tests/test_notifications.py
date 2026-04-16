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

    center.publish(
        NotificationEvent(
            kind="order_submitted",
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            action="BUY",
            confidence=0.82,
            size=0.1,
        )
    )
    center.publish(
        NotificationEvent(
            kind="trade_blocked",
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            action="BUY",
            confidence=0.82,
            detail="reason=risk blocked",
        )
    )
    center.publish(NotificationEvent(kind="runtime_error", detail="err"))

    assert [item[0] for item in transport.messages] == [
        "[TRADE BLOCKED]\nBTC-USDT-SWAP 5m BUY conf=0.82\nreason=risk blocked",
        "[RUNTIME ERROR]\nruntime\nerr",
    ]


def test_notification_center_treats_orders_level_as_critical_only() -> None:
    transport = _Transport()
    center = NotificationCenter(transport=transport, level="orders", cooldown_seconds=60.0)

    center.publish(
        NotificationEvent(
            kind="order_submitted",
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            action="BUY",
            confidence=0.82,
            size=0.1,
        )
    )
    center.publish(
        NotificationEvent(
            kind="order_failed",
            inst_id="BTC-USDT-SWAP",
            detail="rejected",
        )
    )

    assert [item[0] for item in transport.messages] == [
        "[ORDER FAILED]\nBTC-USDT-SWAP\nrejected",
    ]


def test_notification_center_applies_cooldown_per_event_and_inst() -> None:
    transport = _Transport()
    center = NotificationCenter(transport=transport, level="orders", cooldown_seconds=60.0)

    center.publish(NotificationEvent(kind="trade_blocked", inst_id="BTC-USDT-SWAP", detail="blocked-1"))
    center.publish(NotificationEvent(kind="trade_blocked", inst_id="BTC-USDT-SWAP", detail="blocked-2"))
    center.publish(NotificationEvent(kind="trade_blocked", inst_id="ETH-USDT-SWAP", detail="blocked-3"))

    assert [item[0] for item in transport.messages] == [
        "[TRADE BLOCKED]\nBTC-USDT-SWAP\nblocked-1",
        "[TRADE BLOCKED]\nETH-USDT-SWAP\nblocked-3",
    ]
