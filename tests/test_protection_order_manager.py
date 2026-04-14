"""Exchange-side single-OCO protection reconciliation tests."""

from __future__ import annotations

from core.engine.protection import ProtectionThresholds
from core.engine.protection_orders import ProtectionOrderManager


class _DummyOKX:
    def __init__(self, *, positions=None, algo_orders=None):
        self.positions = positions or []
        self.algo_orders = algo_orders or []
        self.placed = []
        self.amended = []
        self.cancelled = []

    def get_positions(self, inst_type="SWAP"):
        return {"data": list(self.positions)}

    def list_algo_orders(self, inst_id=None, ord_type="oco"):
        assert ord_type in {"oco", "conditional"}
        if not inst_id:
            return [item for item in self.algo_orders if item.get("ordType") == ord_type]
        return [
            item
            for item in self.algo_orders
            if item.get("instId") == inst_id and item.get("ordType") == ord_type
        ]

    def place_algo_order(self, **payload):
        self.placed.append(payload)
        return {"code": "0", "data": [{"algoId": "new-algo", "sCode": "0", "sMsg": ""}]}

    def amend_algo_order(self, **payload):
        self.amended.append(payload)
        return {"code": "0", "data": [{"algoId": payload.get("algoId", ""), "sCode": "0", "sMsg": ""}]}

    def cancel_algo_orders(self, entries):
        self.cancelled.append(list(entries))


def test_enforce_places_single_oco_for_live_long_position() -> None:
    client = _DummyOKX(
        positions=[
            {
                "instId": "WLFI-USDT-SWAP",
                "posSide": "net",
                "pos": "8",
                "avgPx": "0.07962875",
                "mgnMode": "isolated",
            }
        ]
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.06, stop_loss_upl_ratio=0.03),
    )

    manager.enforce()

    assert client.cancelled == []
    assert client.amended == []
    assert client.placed == [
        {
            "inst_id": "WLFI-USDT-SWAP",
            "td_mode": "isolated",
            "side": "sell",
            "ord_type": "oco",
            "pos_side": "net",
            "tp_trigger_px": "0.08440648",
            "tp_order_px": "-1",
            "tp_trigger_px_type": "last",
            "sl_trigger_px": "0.07723989",
            "sl_order_px": "-1",
            "sl_trigger_px_type": "last",
            "close_fraction": "1",
            "reduce_only": True,
        }
    ]


def test_enforce_cancels_duplicate_oco_orders_before_recreating() -> None:
    client = _DummyOKX(
        positions=[
            {
                "instId": "WLFI-USDT-SWAP",
                "posSide": "net",
                "pos": "8",
                "avgPx": "0.07962875",
                "mgnMode": "isolated",
            }
        ],
        algo_orders=[
            {"instId": "WLFI-USDT-SWAP", "algoId": "a1", "ordType": "oco", "state": "live"},
            {"instId": "WLFI-USDT-SWAP", "algoId": "a2", "ordType": "oco", "state": "live"},
        ],
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.06, stop_loss_upl_ratio=0.03),
    )

    manager.enforce()

    assert client.cancelled == [[
        {"instId": "WLFI-USDT-SWAP", "algoId": "a1", "ordType": "oco", "state": "live"},
        {"instId": "WLFI-USDT-SWAP", "algoId": "a2", "ordType": "oco", "state": "live"},
    ]]
    assert len(client.placed) == 1
    assert client.amended == []


def test_enforce_cancels_stale_oco_when_position_is_gone() -> None:
    client = _DummyOKX(
        positions=[],
        algo_orders=[
            {"instId": "DOGE-USDT-SWAP", "algoId": "d1", "ordType": "oco", "state": "live"},
        ],
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.06, stop_loss_upl_ratio=0.03),
    )

    manager.enforce()

    assert client.cancelled == [[
        {"instId": "DOGE-USDT-SWAP", "algoId": "d1", "ordType": "oco", "state": "live"},
    ]]
    assert client.placed == []
    assert client.amended == []


def test_enforce_amends_single_existing_oco_when_prices_drift() -> None:
    client = _DummyOKX(
        positions=[
            {
                "instId": "DOGE-USDT-SWAP",
                "posSide": "net",
                "pos": "-0.01",
                "avgPx": "0.09074",
                "mgnMode": "isolated",
            }
        ],
        algo_orders=[
            {
                "instId": "DOGE-USDT-SWAP",
                "algoId": "doge-oco",
                "ordType": "oco",
                "state": "live",
                "side": "buy",
                "posSide": "net",
                "tpTriggerPx": "0.0852",
                "slTriggerPx": "0.0934",
                "tpOrdPx": "-1",
                "slOrdPx": "-1",
                "closeFraction": "1",
            }
        ],
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.06, stop_loss_upl_ratio=0.03),
    )

    manager.enforce()

    assert client.cancelled == []
    assert client.placed == []
    assert client.amended == [
        {
            "inst_id": "DOGE-USDT-SWAP",
            "algo_id": "doge-oco",
            "new_tp_trigger_px": "0.0852956",
            "new_tp_order_px": "-1",
            "new_sl_trigger_px": "0.0934622",
            "new_sl_order_px": "-1",
            "new_tp_trigger_px_type": "last",
            "new_sl_trigger_px_type": "last",
        }
    ]


def test_enforce_places_conditional_order_when_only_stop_loss_is_enabled() -> None:
    client = _DummyOKX(
        positions=[
            {
                "instId": "WLFI-USDT-SWAP",
                "posSide": "net",
                "pos": "8",
                "avgPx": "0.07962875",
                "mgnMode": "isolated",
            }
        ]
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.0, stop_loss_upl_ratio=0.03),
    )

    manager.enforce()

    assert client.placed == [
        {
            "inst_id": "WLFI-USDT-SWAP",
            "td_mode": "isolated",
            "side": "sell",
            "pos_side": "net",
            "ord_type": "conditional",
            "sl_trigger_px": "0.07723989",
            "sl_order_px": "-1",
            "sl_trigger_px_type": "last",
            "close_fraction": "1",
            "reduce_only": True,
        }
    ]


def test_enforce_places_single_oco_from_live_position_leverage() -> None:
    client = _DummyOKX(
        positions=[
            {
                "instId": "PUMP-USDT-SWAP",
                "posSide": "net",
                "pos": "1",
                "avgPx": "0.001917",
                "lever": "10",
                "mgnMode": "isolated",
            }
        ]
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.20, stop_loss_upl_ratio=0.10),
    )

    manager.enforce()

    assert client.placed[0]["tp_trigger_px"] == "0.00195534"
    assert client.placed[0]["sl_trigger_px"] == "0.00189783"
