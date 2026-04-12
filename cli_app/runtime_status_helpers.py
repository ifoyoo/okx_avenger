from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from cli_app.runtime_helpers import DEFAULT_HIGHER_TIMEFRAMES, _human_ratio


def _format_account_lines(account_snapshot: Dict[str, Any]) -> List[str]:
    equity = float(account_snapshot.get("equity") or 0.0)
    available = float(account_snapshot.get("available") or 0.0)
    return [f"equity={equity:.4f} USD available={available:.4f} USD avail={_human_ratio(available, equity)}"]


def _format_watchlist_lines(entries: Iterable[Dict[str, Any]]) -> List[str]:
    rows = list(entries)
    if not rows:
        return ["none"]
    output: List[str] = []
    for idx, item in enumerate(rows, start=1):
        inst = item.get("inst_id")
        tf = item.get("timeframe", "5m")
        higher = ",".join(item.get("higher_timeframes") or DEFAULT_HIGHER_TIMEFRAMES)
        output.append(f"{idx}. {inst} tf={tf} higher={higher}")
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
        active.append(f"{inst} side={side} pos={pos} upl={upl}")
    return active or ["none"]


def _format_heartbeat_lines(path: Path, heartbeat: Optional[Dict[str, Any]]) -> List[str]:
    if not heartbeat:
        return ["none"]
    rows = [f"path={path}"]
    rows.append(
        "updated_at={updated_at} status={status} cycle={cycle} exit_code={exit_code}".format(
            updated_at=heartbeat.get("updated_at", "-"),
            status=heartbeat.get("status", "-"),
            cycle=heartbeat.get("cycle", "-"),
            exit_code=heartbeat.get("exit_code", "-"),
        )
    )
    detail = str(heartbeat.get("detail", "") or "").strip()
    if detail:
        rows.append(f"detail={detail}")
    return rows
