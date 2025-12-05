"""Auto watchlist builder based on market liquidity and account constraints."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger

from config.settings import RuntimeSettings, StrategySettings
from core.client import OKXClient


Number = Optional[float]


class AutoWatchlistBuilder:
    """Generate an automatic watchlist from OKX 24h volume leaders."""

    def __init__(
        self,
        okx_client: OKXClient,
        strategy_settings: StrategySettings,
        runtime_settings: RuntimeSettings,
    ) -> None:
        self.okx = okx_client
        self.strategy_settings = strategy_settings
        self.runtime_settings = runtime_settings
        self.target_size = max(1, int(runtime_settings.auto_watchlist_size))
        self.top_limit = max(self.target_size, int(runtime_settings.auto_watchlist_top_n))
        refresh_hours = max(1, int(runtime_settings.auto_watchlist_refresh_hours))
        self.refresh_window = timedelta(hours=refresh_hours)
        self.cache_path = Path(runtime_settings.auto_watchlist_cache)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.timeframe = (runtime_settings.auto_watchlist_timeframe or "5m").strip() or "5m"
        higher_raw = runtime_settings.auto_watchlist_higher_timeframes or "15m,1H"
        higher_parts = [part.strip() for part in higher_raw.split(",") if part.strip()]
        self.higher_timeframes: Tuple[str, ...] = tuple(higher_parts or ("15m", "1H"))
        self._balance_ratio = max(0.0, float(strategy_settings.balance_usage_ratio))
        leverage = getattr(strategy_settings, "default_leverage", 1.0)
        try:
            leverage_value = float(leverage)
        except (TypeError, ValueError):
            leverage_value = 1.0
        self._leverage = max(1.0, leverage_value)

    def get_entries(self, account_snapshot: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        cached = self._load_cached_entries()
        if cached is not None:
            return cached
        entries = self._build_entries(account_snapshot)
        if entries:
            self._save_cache(entries)
        else:
            logger.warning("自动 watchlist 生成为空，请检查账户资金或筛选条件。")
        return entries

    def _load_cached_entries(self) -> Optional[List[Dict[str, Any]]]:
        if not self.cache_path.exists():
            return None
        try:
            with self.cache_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"读取自动 watchlist 缓存失败: {exc}")
            return None
        updated_at = payload.get("updated_at")
        if not updated_at:
            return None
        try:
            ts = datetime.fromisoformat(updated_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        if datetime.now(timezone.utc) - ts > self.refresh_window:
            return None
        entries = payload.get("entries") or []
        if not isinstance(entries, list):
            return None
        return [self._normalize_entry(entry) for entry in entries if isinstance(entry, dict)]

    def _save_cache(self, entries: Sequence[Dict[str, Any]]) -> None:
        serializable = [self._serialize_entry(entry) for entry in entries]
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "entries": serializable,
        }
        try:
            with self.cache_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"写入自动 watchlist 缓存失败: {exc}")

    def _build_entries(self, account_snapshot: Optional[Dict[str, float]]) -> List[Dict[str, Any]]:
        snapshot = account_snapshot or self._fetch_account_snapshot()
        available = float(snapshot.get("available") or 0.0)
        if available <= 0:
            logger.warning("自动 watchlist：账户可用资金为 0，无法筛选可交易合约。")
            return []
        max_affordable = available * self._balance_ratio * self._leverage
        if max_affordable <= 0:
            logger.warning(f"自动 watchlist：资金限制过低（{max_affordable:.4f}），跳过自动列表。")
            return []
        ticker_data = self._fetch_tickers()
        if not ticker_data:
            return []
        instruments = self._fetch_instruments()
        entries: List[Dict[str, Any]] = []
        skipped_due_to_funds = 0
        for ticker in ticker_data:
            inst_id = ticker.get("instId")
            if not inst_id or not inst_id.upper().endswith("-USDT-SWAP"):
                continue
            meta = instruments.get(inst_id.upper())
            if not meta:
                continue
            last_px = _to_float(ticker.get("last")) or _to_float(ticker.get("px"))
            if last_px <= 0:
                continue
            min_underlying = self._calc_min_underlying(meta, last_px)
            if min_underlying is None or min_underlying <= 0:
                continue
            min_notional = min_underlying * last_px
            if min_notional > max_affordable + 1e-12:
                skipped_due_to_funds += 1
                continue
            entries.append(self._build_entry(inst_id))
            if len(entries) >= self.target_size:
                break
        if not entries and skipped_due_to_funds:
            logger.warning(
                f"自动 watchlist：Top {self.top_limit} 合约中有 {skipped_due_to_funds} 个因资金不足被过滤。"
            )
        elif len(entries) < self.target_size:
            logger.warning(
                f"自动 watchlist：满足资金条件的合约仅 {len(entries)} 个，未达到设定数量 {self.target_size}。"
            )
        return entries

    def _fetch_account_snapshot(self) -> Dict[str, float]:
        try:
            resp = self.okx.get_account_balance()
        except Exception as exc:  # pragma: no cover
            logger.warning(f"自动 watchlist：查询账户余额失败 {exc}")
            return {}
        data = resp.get("data") or []
        if not data:
            return {}
        entry = data[0]
        equity = float(entry.get("totalEq", 0) or 0)
        avail = 0.0
        details = entry.get("details") or []
        if details:
            try:
                avail = sum(float(item.get("availBal", 0) or 0) for item in details)
            except Exception:
                avail = float(entry.get("cashBal", 0) or 0)
        else:
            avail = float(entry.get("cashBal", 0) or 0)
        return {"equity": max(0.0, equity), "available": max(0.0, avail)}

    def _fetch_tickers(self) -> List[Dict[str, Any]]:
        try:
            resp = self.okx.get_tickers("SWAP")
        except Exception as exc:  # pragma: no cover
            logger.warning(f"自动 watchlist：获取 tickers 失败 {exc}")
            return []
        data = resp.get("data") or []
        filtered = [item for item in data if item.get("instId", "").endswith("-USDT-SWAP")]
        filtered.sort(key=lambda item: _to_float(item.get("volCcy24h")), reverse=True)
        return filtered[: self.top_limit]

    def _fetch_instruments(self) -> Dict[str, Dict[str, Any]]:
        try:
            resp = self.okx.instruments(inst_type="SWAP")
        except Exception as exc:  # pragma: no cover
            logger.warning(f"自动 watchlist：获取合约规格失败 {exc}")
            return {}
        data = resp.get("data") or []
        return {str(item.get("instId")).upper(): item for item in data if item.get("instId")}

    def _calc_min_underlying(self, meta: Dict[str, Any], last_px: float) -> Optional[float]:
        min_contracts = _to_float(meta.get("minSz") or meta.get("lotSz"))
        ct_val = _to_float(meta.get("ctVal"))
        if not min_contracts or not ct_val:
            return None
        ct_type = str(meta.get("ctType") or "").lower()
        ct_ccy = str(meta.get("ctValCcy") or "").upper()
        if ct_type in {"", "linear"} or ct_ccy not in {"USD", "USDT", "USDC"}:
            return min_contracts * ct_val
        if last_px <= 0:
            return None
        return (min_contracts * ct_val) / last_px

    def _build_entry(self, inst_id: str) -> Dict[str, Any]:
        return {
            "inst_id": inst_id,
            "timeframe": self.timeframe,
            "higher_timeframes": self.higher_timeframes,
        }

    def _serialize_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        serialized = dict(entry)
        higher = entry.get("higher_timeframes") or ()
        serialized["higher_timeframes"] = list(higher)
        return serialized

    def _normalize_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        higher = entry.get("higher_timeframes") or ()
        if isinstance(higher, str):
            higher_tfs = tuple(part.strip() for part in higher.split(",") if part.strip())
        else:
            higher_tfs = tuple(higher)
        timeframe = entry.get("timeframe") or self.timeframe
        return {
            "inst_id": entry.get("inst_id"),
            "timeframe": timeframe,
            "higher_timeframes": higher_tfs or self.higher_timeframes,
        }


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["AutoWatchlistBuilder"]
