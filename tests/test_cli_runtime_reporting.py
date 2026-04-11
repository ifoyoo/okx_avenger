"""CLI runtime 输出拼装测试。"""

from __future__ import annotations

import importlib
import importlib.util


def _load_reporting():
    assert importlib.util.find_spec("cli_app.runtime_reporting") is not None
    module = importlib.import_module("cli_app.runtime_reporting")
    assert hasattr(module, "format_runtime_status_lines")
    return module


def test_runtime_reporting_module_exists() -> None:
    _load_reporting()


def test_format_runtime_status_lines_with_position_rows() -> None:
    reporting = _load_reporting()
    lines = reporting.format_runtime_status_lines(
        account_lines=["equity"],
        watchlist_lines=["watch"],
        position_lines=["pos"],
        heartbeat_lines=["hb"],
    )

    assert lines == [
        "=== Account ===",
        "equity",
        "",
        "=== Watchlist ===",
        "watch",
        "",
        "=== Position ===",
        "pos",
        "",
        "=== Runtime Heartbeat ===",
        "hb",
    ]


def test_format_runtime_status_lines_with_empty_positions() -> None:
    reporting = _load_reporting()
    lines = reporting.format_runtime_status_lines(
        account_lines=[],
        watchlist_lines=[],
        position_lines=[],
        heartbeat_lines=["hb"],
    )

    assert lines == [
        "=== Account ===",
        "",
        "=== Watchlist ===",
        "",
        "=== Position ===",
        "(no positions)",
        "",
        "=== Runtime Heartbeat ===",
        "hb",
    ]
