"""CLI runtime 单轮执行测试。"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from types import SimpleNamespace

from core.engine.execution import ExecutionPlan
from core.models import SignalAction, TradeSignal


def _load_runtime_execution():
    assert importlib.util.find_spec("cli_app.runtime_execution") is not None
    module = importlib.import_module("cli_app.runtime_execution")
    assert hasattr(module, "run_runtime_cycle")
    assert hasattr(module, "log_strategy_snapshot")
    return module


class _FakeWatchlistManager:
    def __init__(self, entries):
        self.entries = list(entries)
        self.snapshots = []

    def get_watchlist(self, account_snapshot):
        self.snapshots.append(account_snapshot)
        return list(self.entries)


class _FakeOKX:
    def get_account_balance(self):
        return {"data": []}


class _FakeEngine:
    def __init__(self, *, failing_inst_ids=()):
        self.okx = _FakeOKX()
        self.calls = []
        self.failing_inst_ids = set(failing_inst_ids)

    def build_account_snapshot(self, _balance):
        return {"equity": 1000.0, "available": 250.0}

    def run_once(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["inst_id"] in self.failing_inst_ids:
            raise RuntimeError(f"boom:{kwargs['inst_id']}")
        return {
            "signal": TradeSignal(
                action=SignalAction.BUY,
                confidence=0.82,
                reason="test",
                size=0.1,
            ),
            "execution": {
                "plan": ExecutionPlan(
                    inst_id=kwargs["inst_id"],
                    action=SignalAction.BUY,
                    td_mode="cross",
                    pos_side="long",
                    order_type="limit",
                    size=0.1,
                    price=None,
                    est_slippage=0.001,
                )
            },
        }


class _FakePerfTracker:
    def get_snapshot(self):
        return {"trades": 3}

    def get_snapshot_for_days(self, days):
        assert days == 1
        return {"trades": 1}


def _make_bundle(entries, *, failing_inst_ids=()):
    return SimpleNamespace(
        engine=_FakeEngine(failing_inst_ids=failing_inst_ids),
        perf_tracker=_FakePerfTracker(),
        watchlist_manager=_FakeWatchlistManager(entries),
        settings=SimpleNamespace(
            runtime=SimpleNamespace(
                default_max_position=0.25,
            )
        ),
    )


def _make_args(**overrides):
    payload = {
        "inst": None,
        "timeframe": None,
        "higher_timeframes": None,
        "max_position": None,
        "limit": 150,
        "dry_run": False,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_runtime_execution_module_exists() -> None:
    _load_runtime_execution()


def test_run_runtime_cycle_returns_zero_for_empty_watchlist() -> None:
    runtime_execution = _load_runtime_execution()
    bundle = _make_bundle([])

    assert runtime_execution.run_runtime_cycle(bundle, _make_args()) == 0
    assert bundle.engine.calls == []


def test_run_runtime_cycle_executes_single_entry() -> None:
    runtime_execution = _load_runtime_execution()
    bundle = _make_bundle(
        [
            {
                "inst_id": "BTC-USDT-SWAP",
                "timeframe": "15m",
                "higher_timeframes": ("1H", "4H"),
                "max_position": 0.5,
                "protection": {"take_profit": {"mode": "ratio", "value": 0.03}},
            }
        ]
    )

    assert runtime_execution.run_runtime_cycle(bundle, _make_args(limit=200, dry_run=True)) == 0

    assert len(bundle.engine.calls) == 1
    call = bundle.engine.calls[0]
    assert call["inst_id"] == "BTC-USDT-SWAP"
    assert call["timeframe"] == "15m"
    assert call["higher_timeframes"] == ("1H", "4H")
    assert call["max_position"] == 0.5
    assert call["limit"] == 200
    assert call["dry_run"] is True
    assert call["account_snapshot"] == {"equity": 1000.0, "available": 250.0}
    assert call["perf_stats"] == {"trades": 3}
    assert call["daily_stats"] == {"trades": 1}
    assert call["protection_overrides"] == {"take_profit": {"mode": "ratio", "value": 0.03}}


def test_run_runtime_cycle_returns_two_when_all_entries_fail() -> None:
    runtime_execution = _load_runtime_execution()
    bundle = _make_bundle(
        [
            {"inst_id": "BTC-USDT-SWAP"},
            {"inst_id": "ETH-USDT-SWAP"},
        ],
        failing_inst_ids=("BTC-USDT-SWAP", "ETH-USDT-SWAP"),
    )

    assert runtime_execution.run_runtime_cycle(bundle, _make_args()) == 2
    assert [call["inst_id"] for call in bundle.engine.calls] == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]


def test_log_strategy_snapshot_ignores_missing_manager() -> None:
    runtime_execution = _load_runtime_execution()
    bundle = SimpleNamespace(engine=SimpleNamespace(strategy=SimpleNamespace()))

    assert runtime_execution.log_strategy_snapshot(bundle) is None
