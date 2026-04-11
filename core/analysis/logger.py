"""决策日志模块."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, Optional, Tuple

EVAL_LOG_PATH = Path("logs/decisions.jsonl")

# 性能缓存
_PERF_CACHE_MAXLEN = 64
_performance_cache_lock = Lock()
_performance_cache: Dict[Tuple[str, str], Deque[Dict]] = defaultdict(
    lambda: deque(maxlen=_PERF_CACHE_MAXLEN)
)
_performance_cache_loaded = False


@dataclass
class DecisionRecord:
    """决策记录."""

    inst_id: str
    timeframe: str
    timestamp: str
    analysis_action: str
    analysis_confidence: float
    analysis_reason: str
    strategy_action: str
    close_price: float
    trace_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        payload = {
            "inst_id": self.inst_id,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "analysis_action": self.analysis_action,
            "analysis_confidence": self.analysis_confidence,
            "analysis_reason": self.analysis_reason,
            "strategy_action": self.strategy_action,
            "close_price": self.close_price,
        }
        if self.trace_id:
            payload["trace_id"] = self.trace_id
        return payload

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False)


class DecisionLogger:
    """决策日志记录器."""

    def __init__(self, path: Path = EVAL_LOG_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: DecisionRecord) -> None:
        payload = record.as_dict()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        _register_performance_record(payload)


def _load_records(path: Path = EVAL_LOG_PATH) -> list[Dict]:
    """加载历史决策记录."""
    if not path.exists():
        return []
    entries: list[Dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _parse_ts(value: str) -> datetime:
    """解析时间戳."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.min


def _ensure_performance_cache_loaded() -> None:
    """确保性能缓存已加载."""
    global _performance_cache_loaded
    if _performance_cache_loaded:
        return
    with _performance_cache_lock:
        if _performance_cache_loaded:
            return
        entries = _load_records()
        for rec in entries:
            inst = rec.get("inst_id")
            timeframe = rec.get("timeframe")
            if not inst or not timeframe:
                continue
            _performance_cache[(inst, timeframe)].append(rec)
        _performance_cache_loaded = True


def _register_performance_record(record: Dict[str, Any]) -> None:
    """注册性能记录到缓存."""
    inst = record.get("inst_id")
    timeframe = record.get("timeframe")
    if not inst or not timeframe:
        return
    _ensure_performance_cache_loaded()
    with _performance_cache_lock:
        _performance_cache[(inst, timeframe)].append(record)


def build_performance_hint(inst_id: str, timeframe: str, window: int = 30) -> str:
    """构建历史表现提示."""
    _ensure_performance_cache_loaded()
    key = (inst_id, timeframe)
    with _performance_cache_lock:
        cached = list(_performance_cache.get(key, ()))
    if not cached:
        return "历史表现：暂无可用决策记录。"
    records = cached[-(window + 1) :]
    if len(records) < 2:
        return "历史表现：暂无足够数据。"
    records = sorted(
        records, key=lambda rec: _parse_ts(str(rec.get("timestamp") or ""))
    )
    stats: Dict[str, Dict[str, float]] = {}
    for idx in range(len(records) - 1):
        current = records[idx]
        nxt = records[idx + 1]
        action = (current.get("analysis_action") or current.get("llm_action") or "").lower()
        if action not in ("buy", "sell"):
            continue
        curr_price = float(current.get("close_price") or 0.0)
        next_price = float(nxt.get("close_price") or 0.0)
        if curr_price <= 0 or next_price <= 0:
            continue
        direction = 1 if action == "buy" else -1
        move = (next_price - curr_price) * direction
        bucket = stats.setdefault(action, {"total": 0, "wins": 0})
        bucket["total"] += 1
        if move > 0:
            bucket["wins"] += 1
    if not stats:
        return "历史表现：暂无足够数据。"
    parts = []
    for action, result in stats.items():
        total = int(result.get("total", 0))
        wins = int(result.get("wins", 0))
        if total <= 0:
            continue
        win_rate = wins / total
        parts.append(f"{action.upper()} 胜率 {win_rate:.0%} ({wins}/{total})")
    if not parts:
        return "历史表现：暂无足够数据。"
    return "历史表现：" + "；".join(parts)


__all__ = [
    "DecisionLogger",
    "DecisionRecord",
    "build_performance_hint",
]
