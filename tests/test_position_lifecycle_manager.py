from core.models import SignalAction
from core.strategy.lifecycle import build_lifecycle_plan
from core.engine.position_lifecycle import PositionLifecycleManager


class _DummyOKX:
    def __init__(self):
        self.orders = []
        self.response = {"code": "0", "data": [{"ordId": "partial"}]}
        self.positions = [
            {"instId": "BTC-USDT-SWAP", "posSide": "net", "pos": "2", "avgPx": "100", "markPx": "102.3", "mgnMode": "isolated"}
        ]

    def get_positions(self, inst_type="SWAP"):
        return {"data": list(self.positions)}

    def place_order(self, **payload):
        self.orders.append(payload)
        return self.response


def test_position_lifecycle_manager_submits_tp1_partial_and_marks_stage(tmp_path) -> None:
    manager = PositionLifecycleManager(okx_client=_DummyOKX(), state_path=tmp_path / "lifecycle.json")
    manager.register_plan(
        inst_id="BTC-USDT-SWAP",
        pos_side="net",
        size=2.0,
        plan=build_lifecycle_plan(action=SignalAction.BUY, entry_price=100.0, atr=2.0, scale_in_ratio=0.35),
    )

    manager.enforce()

    assert manager.okx.orders[0]["reduce_only"] is True
    assert manager.okx.orders[0]["side"] == "sell"
    assert manager.load_state()["BTC-USDT-SWAP:net"]["tp1_hit"] is True


def test_position_lifecycle_manager_does_not_submit_tp1_twice(tmp_path) -> None:
    manager = PositionLifecycleManager(okx_client=_DummyOKX(), state_path=tmp_path / "lifecycle.json")
    manager.register_plan(
        inst_id="BTC-USDT-SWAP",
        pos_side="net",
        size=2.0,
        plan=build_lifecycle_plan(action=SignalAction.BUY, entry_price=100.0, atr=2.0, scale_in_ratio=0.35),
    )

    manager.enforce()
    manager.enforce()

    assert len(manager.okx.orders) == 1


def test_position_lifecycle_manager_does_not_mark_tp1_when_order_response_fails(tmp_path) -> None:
    okx = _DummyOKX()
    okx.response = {"code": "1", "data": []}
    manager = PositionLifecycleManager(okx_client=okx, state_path=tmp_path / "lifecycle.json")
    manager.register_plan(
        inst_id="BTC-USDT-SWAP",
        pos_side="net",
        size=2.0,
        plan=build_lifecycle_plan(action=SignalAction.BUY, entry_price=100.0, atr=2.0, scale_in_ratio=0.35),
    )

    manager.enforce()

    assert manager.load_state()["BTC-USDT-SWAP:net"]["tp1_hit"] is False


def test_position_lifecycle_manager_matches_single_registered_side_when_exchange_reports_net(tmp_path) -> None:
    manager = PositionLifecycleManager(okx_client=_DummyOKX(), state_path=tmp_path / "lifecycle.json")
    manager.register_plan(
        inst_id="BTC-USDT-SWAP",
        pos_side="long",
        size=2.0,
        plan=build_lifecycle_plan(action=SignalAction.BUY, entry_price=100.0, atr=2.0, scale_in_ratio=0.35),
    )

    manager.enforce()

    assert len(manager.okx.orders) == 1
    assert manager.load_state()["BTC-USDT-SWAP:long"]["tp1_hit"] is True
