from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from cli_app.runtime_helpers import DEFAULT_HIGHER_TIMEFRAMES, _human_ratio


def _format_account_lines(account_snapshot: Dict[str, Any]) -> List[str]:
    equity = float(account_snapshot.get("equity") or 0.0)
    available = float(account_snapshot.get("available") or 0.0)
    return [
        f"equity   : {equity:.4f} USD",
        f"available: {available:.4f} USD",
        f"avail_pct: {_human_ratio(available, equity)}",
    ]


def _format_watchlist_lines(entries: Iterable[Dict[str, Any]]) -> List[str]:
    rows = list(entries)
    if not rows:
        return ["(empty)"]
    output: List[str] = []
    for idx, item in enumerate(rows, start=1):
        inst = item.get("inst_id")
        tf = item.get("timeframe", "5m")
        higher = ",".join(item.get("higher_timeframes") or DEFAULT_HIGHER_TIMEFRAMES)
        output.append(f"{idx:>2}. {inst:<20} tf={tf:<4} higher={higher}")
    return output


def _format_position_lines(positions: Iterable[Dict[str, Any]]) -> List[str]:
    active: List[str] = []
    for item in positions:
        size = str(item.get("pos") or "0")
        if size in ("0", "0.0", "0.00"):
            continue
        inst = item.get("instId", "-")
        side = item.get("posSide") or item.get("side") or "-"
        pos = item.get("pos", "-")
        upl = item.get("upl", "-")
        active.append(f"- {inst:<20} side={side:<5} pos={pos:<12} upl={upl}")
    return active or ["(no active positions)"]


def _format_heartbeat_lines(path: Path, heartbeat: Optional[Dict[str, Any]]) -> List[str]:
    if not heartbeat:
        return ["(no heartbeat)"]
    rows = [
        f"path      : {path}",
        f"updated_at: {heartbeat.get('updated_at', '-')}",
        f"status    : {heartbeat.get('status', '-')}",
        f"cycle     : {heartbeat.get('cycle', '-')}",
        f"exit_code : {heartbeat.get('exit_code', '-')}",
    ]
    detail = str(heartbeat.get("detail", "") or "").strip()
    if detail:
        rows.append(f"detail    : {detail}")
    return rows
