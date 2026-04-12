"""Manual watchlist loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from config.settings import AppSettings
from core.client import OKXClient

DEFAULT_CONFIG_PATH = Path("watchlist.json")
DEFAULT_TIMEFRAME = "5m"
DEFAULT_HIGHER_TIMEFRAMES: Tuple[str, ...] = ("1H",)


def load_watchlist(path: Path = DEFAULT_CONFIG_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Watchlist file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [normalize_entry(entry) for entry in raw]


def normalize_entry(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, str):
        entry = {"inst_id": entry}
    elif not isinstance(entry, dict):
        raise ValueError("watchlist entry must be an object or inst_id string")
    inst_id = str(entry.get("inst_id") or "").strip()
    if not inst_id:
        raise ValueError("watchlist entry missing inst_id")
    timeframe = str(entry.get("timeframe") or DEFAULT_TIMEFRAME).strip()
    higher = entry.get("higher_timeframes")
    if isinstance(higher, str):
        higher_timeframes = tuple(part.strip() for part in higher.split(",") if part.strip())
    elif isinstance(higher, (list, tuple)):
        higher_timeframes = tuple(str(part).strip() for part in higher if str(part).strip())
    else:
        higher_timeframes = DEFAULT_HIGHER_TIMEFRAMES
    result: Dict[str, Any] = {
        "inst_id": inst_id,
        "timeframe": timeframe,
        "higher_timeframes": higher_timeframes or DEFAULT_HIGHER_TIMEFRAMES,
    }
    if "max_position" in entry:
        result["max_position"] = float(entry["max_position"])
    if "protection" in entry and isinstance(entry["protection"], dict):
        result["protection"] = entry["protection"]
    news_query = str(entry.get("news_query") or "").strip()
    if news_query:
        result["news_query"] = news_query
    news_coin_id = str(entry.get("news_coin_id") or "").strip()
    if news_coin_id:
        result["news_coin_id"] = news_coin_id
    raw_aliases = entry.get("news_aliases")
    if isinstance(raw_aliases, str):
        news_aliases = tuple(part.strip() for part in raw_aliases.split(",") if part.strip())
    elif isinstance(raw_aliases, (list, tuple)):
        news_aliases = tuple(str(part).strip() for part in raw_aliases if str(part).strip())
    else:
        news_aliases = ()
    if news_aliases:
        result["news_aliases"] = news_aliases
    return result


class WatchlistManager:
    """Provide runtime watchlist from the manual watchlist file only."""

    def __init__(self, okx_client: OKXClient, settings: AppSettings) -> None:
        self.okx = okx_client
        self.settings = settings
        self._watchlist_path = DEFAULT_CONFIG_PATH
        self._manual_cache: List[Dict[str, Any]] = []
        self._manual_mtime: float = 0.0

    def get_watchlist(self, account_snapshot: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        try:
            return self._load_manual_entries()
        except Exception as exc:
            logger.warning(f"加载手动 watchlist 失败: {exc}")
            return []

    def _load_manual_entries(self) -> List[Dict[str, Any]]:
        path = self._watchlist_path
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            self._manual_cache = []
            self._manual_mtime = 0.0
            raise
        if self._manual_cache and abs(mtime - self._manual_mtime) < 1e-6:
            return list(self._manual_cache)
        entries = load_watchlist(path)
        self._manual_cache = entries
        self._manual_mtime = mtime
        return entries


__all__ = ["load_watchlist", "WatchlistManager"]
