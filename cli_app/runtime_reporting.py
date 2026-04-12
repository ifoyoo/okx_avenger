from __future__ import annotations

from typing import Iterable, List


def format_runtime_status_lines(
    *,
    account_lines: Iterable[str],
    watchlist_lines: Iterable[str],
    position_lines: Iterable[str],
    heartbeat_lines: Iterable[str],
) -> List[str]:
    positions = list(position_lines)
    return [
        "=== Runtime Status ===",
        "",
        "Account",
        *list(account_lines),
        "",
        "Watchlist",
        *list(watchlist_lines),
        "",
        "Positions",
        *(positions or ["none"]),
        "",
        "Heartbeat",
        *list(heartbeat_lines),
    ]
