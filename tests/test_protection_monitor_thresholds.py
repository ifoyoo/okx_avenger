"""ProtectionMonitor per-inst 阈值测试。"""

from __future__ import annotations

from core.engine.protection import ProtectionMonitor, ProtectionThresholds


class _DummyOKX:
    def get_positions(self, inst_type="SWAP"):
        return {"data": []}


def test_resolve_inst_threshold_override() -> None:
    monitor = ProtectionMonitor(
        okx_client=_DummyOKX(),
        thresholds=ProtectionThresholds(take_profit_pct=0.1, stop_loss_pct=0.05),
        per_inst_thresholds={
            "BTC-USDT-SWAP": {"take_profit_pct": 0.03, "stop_loss_pct": 0.02},
        },
    )
    btc = monitor._resolve_threshold("BTC-USDT-SWAP")
    eth = monitor._resolve_threshold("ETH-USDT-SWAP")

    assert btc.take_profit_pct == 0.03
    assert btc.stop_loss_pct == 0.02
    assert eth.take_profit_pct == 0.1
    assert eth.stop_loss_pct == 0.05


def test_evaluate_position_uses_inst_threshold(monkeypatch) -> None:
    monitor = ProtectionMonitor(
        okx_client=_DummyOKX(),
        thresholds=ProtectionThresholds(take_profit_pct=0.1, stop_loss_pct=0.05),
        per_inst_thresholds={
            "BTC-USDT-SWAP": {"take_profit_pct": 0.04, "stop_loss_pct": 0.03},
        },
        cooldown_seconds=5.0,
    )
    called = {"ok": False, "reason": ""}

    def _fake_close(inst_id, pos_side, direction_side, size, margin_mode, reason, profit_ratio):
        called["ok"] = True
        called["reason"] = reason

    monkeypatch.setattr(monitor, "_close_position", _fake_close)
    monitor._evaluate_position(
        {
            "instId": "BTC-USDT-SWAP",
            "pos": "1",
            "avgPx": "100",
            "uplRatio": "0.05",
            "posSide": "long",
            "mgnMode": "cross",
        }
    )

    assert called["ok"] is True
    assert called["reason"] == "take_profit"
