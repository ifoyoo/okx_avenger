"""交易绩效统计与缓存."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, List, Optional

from loguru import logger

from core.client import OKXClient


class PerformanceTracker:
    """基于成交明细计算账户近 N 天的绩效统计."""

    def __init__(
        self,
        okx_client: OKXClient,
        cache_path: Path = Path("data/perf_cache.json"),
        lookback_days: int = 7,
        refresh_minutes: int = 15,
    ) -> None:
        self.okx = okx_client
        self.cache_path = cache_path
        self.lookback_days = max(1, lookback_days)
        self.refresh_minutes = max(5, refresh_minutes)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._state: Dict[str, Any] = self._load_cache() or {}
        self._lock = Lock()
        self._refresh_thread: Optional[Thread] = None

    def get_snapshot(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            stats = self._state.get("stats")
            expired = self._is_expired(self._state)
        if expired:
            self._trigger_refresh()
        return stats

    def get_snapshot_for_days(self, days: int) -> Optional[Dict[str, Any]]:
        days = max(1, days)
        try:
            stats, _ = self._compute_stats_for_days(days)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"获取 {days} 日绩效失败: {exc}")
            return None
        return stats

    def _trigger_refresh(self) -> None:
        with self._lock:
            if self._refresh_thread and self._refresh_thread.is_alive():
                return
            self._refresh_thread = Thread(target=self._refresh_worker, daemon=True)
            self._refresh_thread.start()

    def _refresh_worker(self) -> None:
        try:
            stats, last_id = self._compute_stats_for_days(self.lookback_days)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"更新交易绩效失败: {exc}")
            return
        payload = {
            "last_fill_id": last_id or "",
            "lookback_days": self.lookback_days,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats or {},
        }
        with self._lock:
            self._state = payload
        self._save_cache(payload)

    def _compute_stats_for_days(
        self, days: int
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
        since_ms = int(since_dt.timestamp() * 1000)
        fills = self._fetch_recent_fills(since_ms, days)
        filtered = [
            item for item in fills if self._extract_ts(item) >= since_ms and item.get("fillPnl") is not None
        ]
        if not filtered:
            return None, None
        pnls: List[float] = [self._to_float(item.get("fillPnl") or item.get("pnl")) for item in filtered]
        fees: List[float] = [self._to_float(item.get("fee")) for item in filtered]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total_pnl = sum(pnls)
        total_fee = sum(fees)
        win_rate = 0.0
        decision_count = len(wins) + len(losses)
        if decision_count > 0:
            win_rate = len(wins) / decision_count
        stats = {
            "lookback_days": self.lookback_days,
            "sample_count": len(filtered),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "fee_total": total_fee,
            "period_start": since_dt.isoformat(),
        }
        latest_trade = filtered[0]
        trade_id = str(latest_trade.get("tradeId") or latest_trade.get("billId") or "")
        return stats, trade_id

    def _fetch_recent_fills(self, since_ms: int, lookback_days: int) -> List[Dict[str, Any]]:
        method = (
            self.okx.get_trade_fills_history if lookback_days > 3 else self.okx.get_trade_fills
        )
        limit = 100
        after = ""
        results: List[Dict[str, Any]] = []
        while True:
            resp = method(
                inst_type="SWAP",
                begin=str(since_ms),
                after=after or "",
                limit=limit,
            )
            data = resp.get("data") or []
            if not data:
                break
            results.extend(data)
            last_entry = data[-1]
            after = str(last_entry.get("billId") or last_entry.get("tradeId") or "")
            last_ts = self._extract_ts(last_entry)
            if not after or last_ts < since_ms or len(data) < limit:
                break
        return results

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        if not self.cache_path.exists():
            return None
        try:
            with self.cache_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def _save_cache(self, payload: Dict[str, Any]) -> None:
        try:
            with self.cache_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"写入绩效缓存失败: {exc}")

    def _is_expired(self, cache: Dict[str, Any]) -> bool:
        updated_at = cache.get("updated_at")
        if not updated_at:
            return True
        try:
            ts = datetime.fromisoformat(updated_at)
        except Exception:
            return True
        return datetime.now(timezone.utc) - ts > timedelta(minutes=self.refresh_minutes)

    @staticmethod
    def _extract_ts(entry: Dict[str, Any]) -> int:
        raw = entry.get("ts") or entry.get("fillTime") or entry.get("uTime")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


__all__ = ["PerformanceTracker"]
