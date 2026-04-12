"""CLI config workflow 测试。"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from types import SimpleNamespace


def _load_workflows():
    assert importlib.util.find_spec("cli_app.config_workflows") is not None
    module = importlib.import_module("cli_app.config_workflows")
    assert hasattr(module, "run_config_check")
    return module


def _settings(*, missing=False, llm_enabled=False, news_enabled=False):
    key = "" if missing else "k"
    return SimpleNamespace(
        account=SimpleNamespace(
            okx_api_key=key,
            okx_api_secret=key,
            okx_passphrase=key,
            okx_base_url="https://www.okx.com",
        ),
        runtime=SimpleNamespace(
            run_interval_minutes=5,
            config_snapshot_path="data/config.snapshot.json",
        ),
        strategy=SimpleNamespace(default_leverage=3),
        notification=SimpleNamespace(enabled=True, level="orders"),
        llm=SimpleNamespace(enabled=llm_enabled, model="gpt-x", api_base="https://api.example.com"),
        intel=SimpleNamespace(
            news_enabled=news_enabled,
            news_provider="newsapi",
            news_providers="newsapi,coingecko",
            news_api_base="https://news.example.com",
            coingecko_api_base="https://cg.example.com",
            coingecko_api_key="cg-key",
        ),
    )


def test_config_workflows_module_exists() -> None:
    _load_workflows()


def test_run_config_check_returns_two_when_required_keys_missing(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    monkeypatch.setattr(workflows, "get_settings", lambda: _settings(missing=True))

    assert workflows.run_config_check(argparse.Namespace(api_check=False)) == 2
    assert "❌ 缺少配置项:" in capsys.readouterr().out


def test_run_config_check_prints_snapshot_and_skips_api_check(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    monkeypatch.setattr(workflows, "get_settings", lambda: _settings(llm_enabled=True, news_enabled=True))
    monkeypatch.setattr(workflows, "dump_config_snapshot", lambda settings, path: "data/snapshot.json")

    assert workflows.run_config_check(argparse.Namespace(api_check=False)) == 0

    output = capsys.readouterr().out
    assert "CONFIG READY" in output
    assert "Notify   on level=orders" in output
    assert "LLM      on model=gpt-x base=https://api.example.com" in output
    assert "Intel    on provider=newsapi providers=newsapi,coingecko cg_key=yes" in output
    assert "snapshot data/snapshot.json" in output
    assert "api_check skipped" in output


def test_run_config_check_returns_one_when_api_check_fails(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    monkeypatch.setattr(workflows, "get_settings", lambda: _settings())
    monkeypatch.setattr(workflows, "dump_config_snapshot", lambda settings, path: "data/snapshot.json")
    bundle = SimpleNamespace(
        okx=SimpleNamespace(
            get_account_config=lambda: {"ok": True},
            instruments=lambda inst_type="SWAP": (_ for _ in ()).throw(RuntimeError("api boom")),
        ),
        close=lambda: None,
    )
    monkeypatch.setattr(workflows, "build_runtime", lambda: bundle)

    assert workflows.run_config_check(argparse.Namespace(api_check=True)) == 1
    assert "❌ API 联通性检查失败: api boom" in capsys.readouterr().out


def test_run_config_check_returns_two_when_env_contains_unknown_keys(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    monkeypatch.setattr(workflows, "find_unknown_env_keys", lambda *_args, **_kwargs: ("DEFAULT_LEVERGAE",))

    assert workflows.run_config_check(argparse.Namespace(api_check=False)) == 2
    assert "❌ 检测到未知 .env 配置项: DEFAULT_LEVERGAE" in capsys.readouterr().out
