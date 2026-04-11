"""CLI strategy 输出格式化测试。"""

from __future__ import annotations

from cli_app.strategy_config_helpers import _format_strategy_lines


def test_format_strategy_lines_all_rows() -> None:
    rows = _format_strategy_lines(
        [
            ("bull_trend", True, 1.2),
            ("mean_revert", False, 0.8),
        ]
    )

    assert rows == [
        "=== Strategies ===",
        "name                     enabled  weight  ",
        "-" * 44,
        "bull_trend               yes      1.20    ",
        "mean_revert              no       0.80    ",
    ]


def test_format_strategy_lines_filters_disabled_rows() -> None:
    rows = _format_strategy_lines(
        [
            ("bull_trend", True, 1.2),
            ("mean_revert", False, 0.8),
        ],
        enabled_only=True,
    )

    assert rows == [
        "=== Strategies ===",
        "name                     enabled  weight  ",
        "-" * 44,
        "bull_trend               yes      1.20    ",
    ]
