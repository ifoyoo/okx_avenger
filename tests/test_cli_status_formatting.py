"""CLI status 输出格式化测试。"""

from __future__ import annotations

from pathlib import Path

from cli_app.runtime_status_helpers import (
    _format_account_lines,
    _format_heartbeat_lines,
    _format_position_lines,
    _format_watchlist_lines,
)


def test_format_account_lines() -> None:
    lines = _format_account_lines({"equity": 1000.0, "available": 250.0})
    assert lines == [
        "equity   : 1000.0000 USD",
        "available: 250.0000 USD",
        "avail_pct: 25.0%",
    ]


def test_format_watchlist_lines_empty() -> None:
    assert _format_watchlist_lines([]) == ["(empty)"]


def test_format_watchlist_lines_rows() -> None:
    rows = _format_watchlist_lines(
        [
            {"inst_id": "BTC-USDT-SWAP", "timeframe": "15m", "higher_timeframes": ("1H", "4H")},
        ]
    )
    assert rows == [" 1. BTC-USDT-SWAP        tf=15m  higher=1H,4H"]


def test_format_position_lines_filters_zero_positions() -> None:
    rows = _format_position_lines(
        [
            {"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "0", "upl": "0"},
            {"instId": "ETH-USDT-SWAP", "posSide": "short", "pos": "2", "upl": "12.3"},
        ]
    )
    assert rows == ["- ETH-USDT-SWAP        side=short pos=2            upl=12.3"]


def test_format_heartbeat_lines_with_detail() -> None:
    rows = _format_heartbeat_lines(
        Path("data/runtime_heartbeat.json"),
        {
            "updated_at": "2026-04-11T10:00:00+00:00",
            "status": "error",
            "cycle": 3,
            "exit_code": 2,
            "detail": "boom",
        },
    )
    assert rows == [
        "path      : data/runtime_heartbeat.json",
        "updated_at: 2026-04-11T10:00:00+00:00",
        "status    : error",
        "cycle     : 3",
        "exit_code : 2",
        "detail    : boom",
    ]
