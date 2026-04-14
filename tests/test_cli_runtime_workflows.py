"""CLI runtime workflow 测试。"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_workflows():
    assert importlib.util.find_spec("cli_app.runtime_workflows") is not None
    module = importlib.import_module("cli_app.runtime_workflows")
    assert hasattr(module, "run_runtime_once")
    assert hasattr(module, "show_runtime_status")
    return module


def test_runtime_workflows_module_exists() -> None:
    _load_workflows()


def test_run_runtime_once_writes_running_and_idle_heartbeat(monkeypatch) -> None:
    workflows = _load_workflows()
    writes = []
    monitor = SimpleNamespace(started=0, stopped=0)
    monitor.start = lambda: setattr(monitor, "started", monitor.started + 1)
    monitor.stop = lambda: setattr(monitor, "stopped", monitor.stopped + 1)
    bundle = SimpleNamespace(
        notifier=SimpleNamespace(publish=lambda event: writes.append({"event": event})),
        protection_monitor=monitor,
        settings=SimpleNamespace(runtime=SimpleNamespace(runtime_heartbeat_path="data/runtime-heartbeat.json")),
    )

    monkeypatch.setattr(workflows, "_write_runtime_heartbeat", lambda **kwargs: writes.append(kwargs))
    monkeypatch.setattr(workflows, "log_strategy_snapshot", lambda current: writes.append({"snapshot": current}))
    monkeypatch.setattr(workflows, "run_runtime_cycle", lambda current, args: 7)

    result = workflows.run_runtime_once(bundle, argparse.Namespace())

    assert result == 7
    assert writes[0]["status"] == "running"
    assert writes[0]["cycle"] == 1
    assert writes[1] == {"snapshot": bundle}
    assert writes[2]["status"] == "idle"
    assert writes[2]["exit_code"] == 7
    assert writes[2]["cycle"] == 1
    assert monitor.started == 1
    assert monitor.stopped == 1


def test_run_runtime_once_notifies_runtime_error(monkeypatch) -> None:
    workflows = _load_workflows()
    bundle = SimpleNamespace(
        notifier=SimpleNamespace(events=[], publish=lambda event: bundle.notifier.events.append(event)),
        settings=SimpleNamespace(runtime=SimpleNamespace(runtime_heartbeat_path="data/runtime-heartbeat.json")),
    )

    monkeypatch.setattr(workflows, "_write_runtime_heartbeat", lambda **kwargs: None)
    monkeypatch.setattr(workflows, "log_strategy_snapshot", lambda current: None)
    monkeypatch.setattr(workflows, "run_runtime_cycle", lambda current, args: (_ for _ in ()).throw(RuntimeError("boom")))

    try:
        workflows.run_runtime_once(bundle, argparse.Namespace())
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected runtime error")

    assert len(bundle.notifier.events) == 1
    assert bundle.notifier.events[0].kind == "runtime_error"


def test_sync_protection_orders_configures_watchlist_thresholds_and_enforces(monkeypatch) -> None:
    workflows = _load_workflows()
    monitor = SimpleNamespace(thresholds=[], enforced=0)
    monitor.set_inst_threshold = lambda inst_id, threshold: monitor.thresholds.append((inst_id, threshold))
    monitor.enforce = lambda: setattr(monitor, "enforced", monitor.enforced + 1)
    bundle = SimpleNamespace(
        engine=object(),
        okx=SimpleNamespace(
            get_positions=lambda inst_type="SWAP": {"data": [{"instId": "WLFI-USDT-SWAP", "pos": "8"}]},
            list_algo_orders=lambda ord_type="oco": [{"algoId": "a1", "ordType": ord_type}],
        ),
        watchlist_manager=SimpleNamespace(
            get_watchlist=lambda account_snapshot: [
                {
                    "inst_id": "WLFI-USDT-SWAP",
                    "protection": {
                        "take_profit": {"mode": "percent", "value": 0.05},
                        "stop_loss": {"mode": "percent", "value": 0.02},
                    },
                }
            ]
        ),
        protection_monitor=monitor,
        settings=SimpleNamespace(
            strategy=SimpleNamespace(default_take_profit_upl_ratio=0.06, default_stop_loss_upl_ratio=0.03),
        ),
    )
    info_calls = []

    class _Logger:
        def info(self, message, *args):
            info_calls.append((message, args))

        def warning(self, message, *args):
            return None

    monkeypatch.setattr(workflows, "_safe_account_snapshot", lambda engine: {"equity": 1000.0})
    monkeypatch.setattr(workflows, "logger", _Logger())

    result = workflows.sync_protection_orders(bundle)

    assert result == 0
    assert monitor.thresholds == [
        ("WLFI-USDT-SWAP", {"take_profit_upl_ratio": 0.05, "stop_loss_upl_ratio": 0.02})
    ]
    assert monitor.enforced == 1
    assert info_calls[0] == ("protection sync start positions={} algo_total={}", (1, 2))
    assert info_calls[1] == ("protection sync done positions={} algo_total={}", (1, 2))


def test_sync_protection_orders_returns_one_when_monitor_disabled(monkeypatch) -> None:
    workflows = _load_workflows()
    bundle = SimpleNamespace(
        protection_monitor=None,
        settings=SimpleNamespace(strategy=SimpleNamespace(default_take_profit_upl_ratio=0.0, default_stop_loss_upl_ratio=0.0)),
    )
    warning_calls = []

    class _Logger:
        def info(self, message, *args):
            return None

        def warning(self, message, *args):
            warning_calls.append((message, args))

    monkeypatch.setattr(workflows, "logger", _Logger())

    result = workflows.sync_protection_orders(bundle)

    assert result == 1
    assert warning_calls == [("保护单同步未启用：当前默认止盈止损均为 0。", ())]


def test_show_runtime_status_prints_sections(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    bundle = SimpleNamespace(
        engine=object(),
        watchlist_manager=SimpleNamespace(get_watchlist=lambda account_snapshot: [{"inst_id": "BTC-USDT-SWAP"}]),
        okx=SimpleNamespace(get_positions=lambda inst_type="SWAP": {"data": []}),
        settings=SimpleNamespace(runtime=SimpleNamespace(runtime_heartbeat_path="data/runtime_heartbeat.json")),
    )

    monkeypatch.setattr(workflows, "_safe_account_snapshot", lambda engine: {"equity": 1000.0})
    monkeypatch.setattr(workflows, "_format_account_lines", lambda snapshot: ["equity line"])
    monkeypatch.setattr(workflows, "_format_watchlist_lines", lambda entries: ["watchlist line"])
    monkeypatch.setattr(workflows, "_format_position_lines", lambda positions: ["position line"])
    monkeypatch.setattr(workflows, "_read_runtime_heartbeat", lambda path: {"status": "idle"})
    monkeypatch.setattr(workflows, "_format_heartbeat_lines", lambda path, heartbeat: ["heartbeat line"])

    result = workflows.show_runtime_status(bundle)

    assert result == 0
    output = capsys.readouterr().out
    assert "=== Runtime Status ===" in output
    assert "Account" in output
    assert "Watchlist" in output
    assert "Positions" in output
    assert "Heartbeat" in output
    assert "equity line" in output
    assert "watchlist line" in output
    assert "none" in output
    assert "heartbeat line" in output


def test_show_runtime_status_returns_one_when_position_query_fails(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    bundle = SimpleNamespace(
        engine=object(),
        watchlist_manager=SimpleNamespace(get_watchlist=lambda account_snapshot: []),
        okx=SimpleNamespace(
            get_positions=lambda inst_type="SWAP": (_ for _ in ()).throw(RuntimeError("position boom"))
        ),
        settings=SimpleNamespace(runtime=SimpleNamespace(runtime_heartbeat_path="data/runtime_heartbeat.json")),
    )

    monkeypatch.setattr(workflows, "_safe_account_snapshot", lambda engine: {})
    monkeypatch.setattr(workflows, "_format_account_lines", lambda snapshot: [])
    monkeypatch.setattr(workflows, "_format_watchlist_lines", lambda entries: [])

    result = workflows.show_runtime_status(bundle)

    assert result == 1
    assert "query failed: position boom" in capsys.readouterr().out
