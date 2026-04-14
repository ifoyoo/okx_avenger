"""ExecutionEngine clOrdId 幂等测试。"""

from __future__ import annotations

from types import SimpleNamespace

from core.engine.execution import ExecutionEngine, ExecutionPlan
from core.models import ProtectionRule, SignalAction, TradeProtection, TradeSignal


class _DummyOKXClient:
    def __init__(self) -> None:
        self.last_place_order = None

    def instruments(self, inst_type: str = "SWAP"):
        return {"data": []}

    def place_order(self, **kwargs):
        self.last_place_order = kwargs
        return {"code": "0", "data": [{"ordId": "123"}]}


class _PendingOKXClient(_DummyOKXClient):
    def get_positions(self, inst_type: str = "SWAP"):
        return {"data": [{"instId": "BTC-USDT-SWAP", "pos": "0"}]}

    def list_pending_orders(self, inst_id: str | None = None):
        return []


class _LivePendingLimitOKXClient(_PendingOKXClient):
    def list_pending_orders(self, inst_id: str | None = None):
        return [
            {
                "instId": "BTC-USDT-SWAP",
                "clOrdId": "fixed-clordid-002",
                "state": "live",
                "ordType": "limit",
            }
        ]


def test_build_plan_generates_cl_ord_id_with_trace(monkeypatch) -> None:
    monkeypatch.setattr("core.engine.execution.uuid.uuid4", lambda: SimpleNamespace(hex="f" * 32))
    client = _DummyOKXClient()
    engine = ExecutionEngine(client)
    signal = TradeSignal(
        action=SignalAction.BUY,
        confidence=0.8,
        reason="x",
        size=0.01,
    )

    plan = engine.build_plan(
        inst_id="BTC-USDT-SWAP",
        signal=signal,
        td_mode="cross",
        pos_side="long",
        latest_price=100.0,
        atr=1.0,
        trace_id="traceabc123456",
    )

    assert plan.cl_ord_id is not None
    assert len(plan.cl_ord_id) <= 32
    assert "traceabc" in plan.cl_ord_id


def test_execute_uses_existing_cl_ord_id() -> None:
    client = _DummyOKXClient()
    engine = ExecutionEngine(client)
    plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.01,
        price=None,
        est_slippage=0.0,
        blocked=False,
        cl_ord_id="fixed-clordid-001",
    )

    report = engine.execute(plan)

    assert report.success is True
    assert client.last_place_order is not None
    assert client.last_place_order["cl_ord_id"] == "fixed-clordid-001"


def test_execute_auto_generates_cl_ord_id_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("core.engine.execution.uuid.uuid4", lambda: SimpleNamespace(hex="a" * 32))
    client = _DummyOKXClient()
    engine = ExecutionEngine(client)
    plan = ExecutionPlan(
        inst_id="ETH-USDT-SWAP",
        action=SignalAction.SELL,
        td_mode="cross",
        pos_side="short",
        order_type="market",
        size=0.02,
        price=None,
        est_slippage=0.0,
        blocked=False,
        cl_ord_id=None,
    )

    report = engine.execute(plan)

    assert report.success is True
    assert client.last_place_order is not None
    generated = client.last_place_order.get("cl_ord_id")
    assert isinstance(generated, str) and generated
    assert len(generated) <= 32


def test_execute_pending_timeout_when_no_position(monkeypatch) -> None:
    monkeypatch.setattr("core.engine.execution.time.sleep", lambda _s: None)
    client = _PendingOKXClient()
    engine = ExecutionEngine(client, pending_timeout_seconds=0.01, reconcile_position=True)
    plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="market",
        size=0.01,
        price=None,
        est_slippage=0.0,
        blocked=False,
        cl_ord_id="fixed-clordid-002",
    )

    report = engine.execute(plan)

    assert report.success is False
    assert report.code == "PENDING_TIMEOUT"


def test_execute_treats_live_limit_order_as_submitted(monkeypatch) -> None:
    monkeypatch.setattr("core.engine.execution.time.sleep", lambda _s: None)
    client = _LivePendingLimitOKXClient()
    engine = ExecutionEngine(client, pending_timeout_seconds=0.01, reconcile_position=True)
    plan = ExecutionPlan(
        inst_id="BTC-USDT-SWAP",
        action=SignalAction.BUY,
        td_mode="cross",
        pos_side="long",
        order_type="limit",
        size=0.01,
        price=100.0,
        est_slippage=0.0,
        blocked=False,
        cl_ord_id="fixed-clordid-002",
    )

    report = engine.execute(plan)

    assert report.success is True
    assert report.code is None


def test_build_plan_resolves_attach_algo_orders_from_trade_protection() -> None:
    client = _DummyOKXClient()
    engine = ExecutionEngine(client)
    signal = TradeSignal(
        action=SignalAction.BUY,
        confidence=0.55,
        reason="x",
        size=0.01,
        protection=TradeProtection(
            take_profit=ProtectionRule(mode="rr", value=2.0),
            stop_loss=ProtectionRule(mode="ratio", value=0.01),
        ),
    )

    plan = engine.build_plan(
        inst_id="BTC-USDT-SWAP",
        signal=signal,
        td_mode="cross",
        pos_side="long",
        latest_price=100.0,
        atr=1.0,
        trace_id="tp-sl-redesign",
    )
    payload = engine._build_attach_algo_orders(plan.protection)

    assert payload == [
        {
            "tpTriggerPx": "102",
            "tpTriggerPxType": "last",
            "tpOrdPx": "-1",
            "tpOrdKind": "condition",
            "slTriggerPx": "99",
            "slTriggerPxType": "last",
            "slOrdPx": "-1",
            "slOrdKind": "condition",
        }
    ]


def test_build_plan_resolves_attach_algo_orders_from_upl_ratio_protection() -> None:
    client = _DummyOKXClient()
    engine = ExecutionEngine(client)
    signal = TradeSignal(
        action=SignalAction.BUY,
        confidence=0.7,
        reason="x",
        size=0.01,
        protection=TradeProtection(
            take_profit=ProtectionRule(mode="percent", value=0.20),
            stop_loss=ProtectionRule(mode="percent", value=0.10),
        ),
    )

    plan = engine.build_plan(
        inst_id="BTC-USDT-SWAP",
        signal=signal,
        td_mode="cross",
        pos_side="long",
        latest_price=100.0,
        atr=0.0,
        leverage=10.0,
        trace_id="uplratio",
    )
    payload = engine._build_attach_algo_orders(plan.protection)

    assert payload == [
        {
            "tpTriggerPx": "102",
            "tpTriggerPxType": "last",
            "tpOrdPx": "-1",
            "tpOrdKind": "condition",
            "slTriggerPx": "99",
            "slTriggerPxType": "last",
            "slOrdPx": "-1",
            "slOrdKind": "condition",
        }
    ]
