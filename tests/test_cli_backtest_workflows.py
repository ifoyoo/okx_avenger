"""CLI backtest workflow 测试。"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_workflows():
    assert importlib.util.find_spec("cli_app.backtest_workflows") is not None
    module = importlib.import_module("cli_app.backtest_workflows")
    assert hasattr(module, "run_backtest_for_bundle")
    assert hasattr(module, "report_backtest")
    assert hasattr(module, "tune_backtest_for_bundle")
    return module


class _FakeWatchlistManager:
    def __init__(self, entries):
        self.entries = list(entries)

    def get_watchlist(self, _account_snapshot):
        return list(self.entries)


class _FakeOKX:
    def get_account_balance(self):
        return {"data": []}


class _FakeEngine:
    def __init__(self):
        self.okx = _FakeOKX()
        self.leverage = 3
        self.strategy = SimpleNamespace(
            signal_generator=SimpleNamespace(plugin_manager=object())
        )

    def build_account_snapshot(self, _balance):
        return {"equity": 1000.0}


def _make_bundle(entries):
    return SimpleNamespace(
        okx=_FakeOKX(),
        engine=_FakeEngine(),
        watchlist_manager=_FakeWatchlistManager(entries),
        settings=SimpleNamespace(
            runtime=SimpleNamespace(default_max_position=0.25)
        ),
    )


def _make_run_args(**overrides):
    payload = {
        "inst": None,
        "timeframe": None,
        "higher_timeframes": None,
        "max_position": None,
        "limit": 150,
        "warmup": 50,
        "initial_equity": 10000.0,
        "fee_rate": 0.001,
        "slippage_ratio": 0.0,
        "spread_ratio": 0.0,
        "max_hold_bars": 0,
        "apply": False,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_backtest_workflows_module_exists() -> None:
    _load_workflows()


def test_run_backtest_for_bundle_returns_two_for_empty_watchlist(capsys) -> None:
    workflows = _load_workflows()

    result = workflows.run_backtest_for_bundle(_make_bundle([]), _make_run_args())

    assert result == 2
    assert "watchlist 为空，无法回测。" in capsys.readouterr().out


def test_tune_backtest_for_bundle_returns_two_for_empty_watchlist(capsys) -> None:
    workflows = _load_workflows()

    result = workflows.tune_backtest_for_bundle(_make_bundle([]), _make_run_args())

    assert result == 2
    assert "watchlist 为空，无法调参。" in capsys.readouterr().out


def test_report_backtest_filters_inst_and_limits_trades(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    summary_calls = []

    records = [
        {
            "summary": {"inst_id": "BTC-USDT-SWAP", "timeframe": "5m"},
            "trades": [
                {"side": "buy", "qty": 1, "entry_price": 10, "exit_price": 11, "net_pnl": 1, "bars_held": 3},
                {"side": "sell", "qty": 2, "entry_price": 20, "exit_price": 19, "net_pnl": -2, "bars_held": 5},
                {"side": "buy", "qty": 3, "entry_price": 30, "exit_price": 32, "net_pnl": 6, "bars_held": 8},
            ],
        },
        {
            "summary": {"inst_id": "ETH-USDT-SWAP", "timeframe": "15m"},
            "trades": [{"side": "sell", "qty": 4, "entry_price": 40, "exit_price": 35, "net_pnl": 20, "bars_held": 13}],
        },
    ]

    monkeypatch.setattr(workflows, "_load_backtest_records", lambda _path: records)
    monkeypatch.setattr(
        workflows,
        "_print_backtest_summary",
        lambda current: summary_calls.append([item["summary"]["inst_id"] for item in current]),
    )

    args = argparse.Namespace(
        file=None,
        inst="btc-usdt-swap",
        show_trades=True,
        max_trades=2,
    )

    result = workflows.report_backtest(args)

    assert result == 0
    assert summary_calls == [["BTC-USDT-SWAP"]]
    output = capsys.readouterr().out
    assert "[BTC-USDT-SWAP 5m]" in output
    assert "qty=3.000000" in output
    assert "qty=2.000000" in output
    assert "qty=1.000000" not in output


def test_report_backtest_returns_two_when_file_missing(monkeypatch, capsys) -> None:
    workflows = _load_workflows()
    monkeypatch.setattr(workflows, "_load_backtest_records", lambda _path: [])

    result = workflows.report_backtest(
        argparse.Namespace(file=str(Path("missing.json")), inst=None, show_trades=False, max_trades=5)
    )

    assert result == 2
    assert "未找到回测结果:" in capsys.readouterr().out
