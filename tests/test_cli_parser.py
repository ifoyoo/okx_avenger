"""CLI 参数解析测试。"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from cli import build_parser
from cli_app.backtest_parser import register_backtest_commands
from cli_app.config_parser import register_config_commands
import cli_app.runtime_parser as runtime_parser
from cli_app.runtime_parser import register_runtime_commands
from cli_app.strategies_parser import register_strategy_commands


def test_once_command_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "once",
            "--inst",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--higher-timeframes",
            "1H,4H",
            "--dry-run",
        ]
    )

    assert args.command == "once"
    assert args.inst == "BTC-USDT-SWAP"
    assert args.timeframe == "15m"
    assert args.higher_timeframes == "1H,4H"
    assert args.dry_run is True


def test_config_check_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["config-check", "--api-check"])
    assert args.command == "config-check"
    assert args.api_check is True


def test_strategies_list_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["strategies", "list", "--enabled-only"])
    assert args.command == "strategies"
    assert args.strategy_action == "list"
    assert args.enabled_only is True


def test_strategies_set_weight_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["strategies", "set-weight", "bull_trend", "1.3"])
    assert args.command == "strategies"
    assert args.strategy_action == "set-weight"
    assert args.name == "bull_trend"
    assert args.weight == 1.3


def test_strategies_enable_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["strategies", "enable", "bull_trend", "ma_golden_cross"])
    assert args.command == "strategies"
    assert args.strategy_action == "enable"
    assert args.names == ["bull_trend", "ma_golden_cross"]


def test_backtest_run_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["backtest", "run", "--inst", "BTC-USDT-SWAP", "--limit", "800"])
    assert args.command == "backtest"
    assert args.backtest_action == "run"
    assert args.inst == "BTC-USDT-SWAP"
    assert args.limit == 800


def test_backtest_tune_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["backtest", "tune", "--inst", "BTC-USDT-SWAP", "--apply"])
    assert args.command == "backtest"
    assert args.backtest_action == "tune"
    assert args.inst == "BTC-USDT-SWAP"
    assert args.apply is True


def test_runtime_parser_module_registers_status() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    register_runtime_commands(sub)

    args = parser.parse_args(["status"])

    assert args.command == "status"


def test_runtime_parser_uses_feature_limit_setting(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_parser,
        "get_settings",
        lambda: SimpleNamespace(runtime=SimpleNamespace(feature_limit=240)),
    )
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    register_runtime_commands(sub)
    args = parser.parse_args(["once", "--inst", "BTC-USDT-SWAP"])

    assert args.limit == 240


def test_config_parser_module_registers_api_check() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    register_config_commands(sub)

    args = parser.parse_args(["config-check", "--api-check"])

    assert args.command == "config-check"
    assert args.api_check is True


def test_strategies_parser_module_registers_enable() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    register_strategy_commands(sub)

    args = parser.parse_args(["strategies", "enable", "bull_trend"])

    assert args.command == "strategies"
    assert args.strategy_action == "enable"
    assert args.names == ["bull_trend"]


def test_backtest_parser_module_registers_report() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    register_backtest_commands(sub)

    args = parser.parse_args(["backtest", "report", "--file", "sample.json", "--show-trades"])

    assert args.command == "backtest"
    assert args.backtest_action == "report"
    assert args.file == "sample.json"
    assert args.show_trades is True
