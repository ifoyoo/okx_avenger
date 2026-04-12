"""CLI backtest 输出格式化测试。"""

from __future__ import annotations

import importlib
import importlib.util


def _load_reporting():
    assert importlib.util.find_spec("cli_app.backtest_reporting") is not None
    module = importlib.import_module("cli_app.backtest_reporting")
    assert hasattr(module, "format_backtest_summary_lines")
    assert hasattr(module, "format_trade_lines")
    assert hasattr(module, "format_tune_lines")
    return module


def test_backtest_reporting_module_exists() -> None:
    _load_reporting()


def test_format_backtest_summary_lines_adds_report_summary() -> None:
    reporting = _load_reporting()
    lines = reporting.format_backtest_summary_lines(
        [
            {
                "summary": {
                    "inst_id": "BTC-USDT-SWAP",
                    "timeframe": "5m",
                    "total_trades": 10,
                    "win_rate": 0.6,
                    "net_pnl": 120.0,
                    "max_drawdown": 0.08,
                }
            },
            {
                "summary": {
                    "inst_id": "ETH-USDT-SWAP",
                    "timeframe": "15m",
                    "total_trades": 8,
                    "win_rate": 0.5,
                    "net_pnl": 80.0,
                    "max_drawdown": 0.12,
                }
            },
        ]
    )

    assert lines[0] == "=== Backtest Report ==="
    assert lines[1] == "summary records=2 total_trades=18 net_pnl=+200.00 best=BTC-USDT-SWAP"
    assert "inst" in lines[3]
    assert any("BTC-USDT-SWAP" in line for line in lines)


def test_format_trade_lines_limits_latest_rows() -> None:
    reporting = _load_reporting()
    records = [
        {
            "summary": {"inst_id": "BTC-USDT-SWAP", "timeframe": "5m"},
            "trades": [
                {"side": "buy", "qty": 1, "entry_price": 10, "exit_price": 11, "net_pnl": 1, "bars_held": 3},
                {"side": "sell", "qty": 2, "entry_price": 20, "exit_price": 19, "net_pnl": -2, "bars_held": 5},
                {"side": "buy", "qty": 3, "entry_price": 30, "exit_price": 32, "net_pnl": 6, "bars_held": 8},
            ],
        }
    ]

    lines = reporting.format_trade_lines(records, max_trades=2)

    assert lines == [
        "",
        "=== Trade Samples ===",
        "",
        "[BTC-USDT-SWAP 5m latest=2]",
        "- BUY  qty=3.000000 entry=30.000000 exit=32.000000 net=+6.0000 held=8",
        "- SELL qty=2.000000 entry=20.000000 exit=19.000000 net=-2.0000 held=5",
    ]


def test_format_tune_lines_contains_scoreboard_and_regimes() -> None:
    reporting = _load_reporting()

    lines = reporting.format_tune_lines(
        lookback_bars=150,
        scanned_instruments=2,
        scores={"beta": 0.4, "alpha": 0.8},
        weights={"beta": 0.9, "alpha": 1.4},
        stats_rows={
            "alpha": [(10, 60.0, 120.0), (8, 50.0, 80.0)],
            "beta": [(6, 40.0, -10.0)],
        },
        regime_score_buckets={
            "high_vol": {"alpha": [0.7, 0.9], "beta": [0.1]},
            "low_vol": {"alpha": [], "beta": []},
        },
    )

    assert lines[0] == "=== Backtest Tune ==="
    assert lines[1] == "leader=alpha score=+0.8000 scanned=2 lookback=150"
    assert any(line.startswith("alpha") and "1.40" in line for line in lines)
    assert any(line.startswith("beta") and "0.90" in line for line in lines)
    assert "[high_vol]" in lines
    assert "- alpha" in " ".join(lines)
    assert "- (no data)" in lines
