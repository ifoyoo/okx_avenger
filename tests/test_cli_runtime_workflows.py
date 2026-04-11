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
    bundle = SimpleNamespace(
        settings=SimpleNamespace(runtime=SimpleNamespace(runtime_heartbeat_path="data/runtime-heartbeat.json"))
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
    assert "=== Account ===" in output
    assert "=== Watchlist ===" in output
    assert "=== Position ===" in output
    assert "=== Runtime Heartbeat ===" in output
    assert "equity line" in output
    assert "watchlist line" in output
    assert "(no positions)" in output
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
