"""CLI strategy workflow 测试。"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from types import SimpleNamespace


def _load_workflows():
    assert importlib.util.find_spec("cli_app.strategy_workflows") is not None
    module = importlib.import_module("cli_app.strategy_workflows")
    assert hasattr(module, "run_strategy_action")
    return module


def _args(**overrides):
    payload = {
        "strategy_action": "list",
        "enabled_only": False,
        "names": [],
        "name": "",
        "weight": 1.0,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_strategy_workflows_module_exists() -> None:
    _load_workflows()


def test_run_strategy_action_dispatches_list(monkeypatch) -> None:
    workflows = _load_workflows()
    printed = []
    settings = SimpleNamespace()

    monkeypatch.setattr(workflows, "_refresh_settings_cache", lambda: None)
    monkeypatch.setattr(workflows, "get_settings", lambda: settings)
    monkeypatch.setattr(workflows, "_strategy_names_from_settings", lambda _settings: ["bull_trend"])
    monkeypatch.setattr(
        workflows,
        "_print_strategies",
        lambda current, enabled_only=False: printed.append((current, enabled_only)),
    )

    assert workflows.run_strategy_action(_args(enabled_only=True)) == 0
    assert printed == [(settings, True)]


def test_run_strategy_action_returns_two_for_unknown_enable_target(monkeypatch, capsys) -> None:
    workflows = _load_workflows()

    monkeypatch.setattr(workflows, "_refresh_settings_cache", lambda: None)
    monkeypatch.setattr(workflows, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(workflows, "_strategy_names_from_settings", lambda _settings: ["bull_trend"])
    monkeypatch.setattr(workflows, "_normalize_names", lambda names, available: ([], ["missing_plugin"]))

    assert workflows.run_strategy_action(_args(strategy_action="enable", names=["missing_plugin"])) == 2
    assert "❌ 未知策略：" in capsys.readouterr().out


def test_run_strategy_action_clamps_weight_before_saving(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    saved = {}

    monkeypatch.setattr(workflows, "_refresh_settings_cache", lambda: None)
    monkeypatch.setattr(workflows, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(workflows, "_strategy_names_from_settings", lambda _settings: ["bull_trend"])
    monkeypatch.setattr(workflows, "_normalize_names", lambda names, available: (["bull_trend"], []))
    monkeypatch.setattr(workflows, "_current_weight_map", lambda settings, names: {})

    def _save(weights, names):
        saved["weights"] = dict(weights)
        saved["names"] = list(names)
        return "bull_trend=3.00"

    monkeypatch.setattr(workflows, "_save_weight_config", _save)
    monkeypatch.setattr(workflows, "_print_strategies", lambda _settings, enabled_only=False: None)

    assert workflows.run_strategy_action(_args(strategy_action="set-weight", name="bull_trend", weight=9.5)) == 0
    assert saved["weights"] == {"bull_trend": 3.0}
    assert "✅ STRATEGY_SIGNAL_WEIGHTS=bull_trend=3.00" in capsys.readouterr().out


def test_run_strategy_action_returns_two_for_unsupported_action(monkeypatch, capsys) -> None:
    workflows = _load_workflows()

    monkeypatch.setattr(workflows, "_refresh_settings_cache", lambda: None)
    monkeypatch.setattr(workflows, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(workflows, "_strategy_names_from_settings", lambda _settings: ["bull_trend"])

    assert workflows.run_strategy_action(_args(strategy_action="boom")) == 2
    assert "❌ 不支持的操作: boom" in capsys.readouterr().out
