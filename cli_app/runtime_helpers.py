from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from core.data.watchlist_loader import WatchlistManager
from core.engine.execution import ExecutionPlan
from core.engine.trading import TradingEngine
DEFAULT_LIMIT = 150
DEFAULT_TIMEFRAME = "5m"
DEFAULT_HIGHER_TIMEFRAMES: Tuple[str, ...] = ("1H",)


def _parse_timeframes(raw: str) -> Tuple[str, ...]:
    parts = [part.strip() for part in (raw or "").split(",") if part.strip()]
    return tuple(parts)


def _fmt_plan(plan: Optional[ExecutionPlan]) -> str:
    if not plan:
        return "no-plan"
    if plan.blocked:
        return f"BLOCKED({plan.block_reason or 'unknown'})"
    return f"{plan.order_type.upper()} slip={plan.est_slippage:.2%}"


def _safe_account_snapshot(engine: TradingEngine) -> Dict[str, float]:
    try:
        balance = engine.okx.get_account_balance()
        return engine.build_account_snapshot(balance)
    except Exception as exc:
        logger.warning("获取账户快照失败: {}", exc)
        return {}


def _resolve_entries(
    *,
    args: argparse.Namespace,
    watchlist_manager: WatchlistManager,
    account_snapshot: Dict[str, float],
    default_max_position: float,
) -> List[Dict[str, Any]]:
    if args.inst:
        higher = _parse_timeframes(args.higher_timeframes or "")
        return [
            {
                "inst_id": args.inst,
                "timeframe": args.timeframe or DEFAULT_TIMEFRAME,
                "higher_timeframes": higher or DEFAULT_HIGHER_TIMEFRAMES,
                "max_position": args.max_position or default_max_position,
            }
        ]
    return watchlist_manager.get_watchlist(account_snapshot)


def _write_runtime_heartbeat(
    *,
    path: Path,
    status: str,
    cycle: int = 0,
    exit_code: int = 0,
    detail: str = "",
) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "cycle": int(cycle),
        "exit_code": int(exit_code),
        "detail": str(detail or ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _read_runtime_heartbeat(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _human_ratio(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{(numerator / denominator) * 100:.1f}%"
