"""Runtime enforcement of take-profit / stop-loss thresholds."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from loguru import logger

from .client import OKXClient


@dataclass
class ProtectionThresholds:
    take_profit_pct: float
    stop_loss_pct: float


class ProtectionMonitor:
    """Actively monitors open positions and closes them when TP/SL is hit."""

    def __init__(
        self,
        okx_client: OKXClient,
        thresholds: ProtectionThresholds,
        default_td_mode: str = "cross",
        cooldown_seconds: float = 30.0,
        interval_seconds: float = 15.0,
    ) -> None:
        self.okx = okx_client
        self.thresholds = thresholds
        self.default_td_mode = (default_td_mode or "cross").lower() or "cross"
        self.cooldown_seconds = max(5.0, cooldown_seconds)
        self.interval_seconds = max(5.0, interval_seconds)
        self._cooldown: Dict[str, float] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="protection-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.enforce()
            self._stop_event.wait(self.interval_seconds)

    def enforce(self) -> None:
        try:
            resp = self.okx.get_positions(inst_type="SWAP")
        except Exception as exc:  # pragma: no cover
            logger.warning(f"查询持仓失败，无法执行保护：{exc}")
            return
        data = resp.get("data") or []
        for entry in data:
            self._evaluate_position(entry)

    def _evaluate_position(self, entry: Dict[str, str]) -> None:
        try:
            inst_id = str(entry.get("instId") or "").strip()
            if not inst_id:
                return
            raw_size = float(entry.get("pos") or 0.0)
            if abs(raw_size) <= 0:
                return
            avg_px = float(entry.get("avgPx") or 0.0)
            pos_side_raw = (entry.get("posSide") or "").strip().lower()
            direction_side = self._infer_direction(pos_side_raw, raw_size)
            if not direction_side:
                return
            direction_sign = 1 if direction_side == "long" else -1
            profit_ratio = self._extract_profit_ratio(entry, avg_px, direction_sign)
            if profit_ratio is None:
                return
            key = f"{inst_id}:{direction_side}"
            now = time.time()
            if now - self._cooldown.get(key, 0.0) < self.cooldown_seconds:
                return
            margin_mode = entry.get("mgnMode") or entry.get("marginMode")
            if self.thresholds.take_profit_pct > 0 and profit_ratio >= self.thresholds.take_profit_pct:
                self._close_position(
                    inst_id,
                    pos_side_raw,
                    direction_side,
                    abs(raw_size),
                    margin_mode,
                    "take_profit",
                    profit_ratio,
                )
                self._cooldown[key] = now
            elif self.thresholds.stop_loss_pct > 0 and profit_ratio <= -self.thresholds.stop_loss_pct:
                self._close_position(
                    inst_id,
                    pos_side_raw,
                    direction_side,
                    abs(raw_size),
                    margin_mode,
                    "stop_loss",
                    profit_ratio,
                )
                self._cooldown[key] = now
        except Exception as exc:  # pragma: no cover
            logger.warning(f"强制保护计算异常 inst={entry.get('instId')} err={exc}")

    @staticmethod
    def _infer_direction(pos_side_raw: str, raw_size: float) -> Optional[str]:
        normalized = (pos_side_raw or "").lower()
        if normalized in {"long", "short"}:
            return normalized
        if raw_size > 0:
            return "long"
        if raw_size < 0:
            return "short"
        return None

    @staticmethod
    def _extract_profit_ratio(entry: Dict[str, str], avg_px: float, direction: int) -> Optional[float]:
        upl_ratio_text = entry.get("uplRatio")
        if upl_ratio_text not in ("", None):
            try:
                ratio = float(upl_ratio_text)
            except (TypeError, ValueError):
                ratio = None
            else:
                if abs(ratio) > 5:  # uplRatio 通常是百分数
                    ratio /= 100.0
                return ratio
        mark_px = float(entry.get("markPx") or entry.get("last") or 0.0)
        if avg_px <= 0 or mark_px <= 0:
            return None
        return direction * (mark_px - avg_px) / avg_px

    def _close_position(
        self,
        inst_id: str,
        pos_side: Optional[str],
        direction_side: str,
        size: float,
        margin_mode: Optional[str],
        reason: str,
        profit_ratio: float,
    ) -> None:
        if size <= 0:
            return
        order_side = "sell" if direction_side == "long" else "buy"
        td_mode = (margin_mode or self.default_td_mode or "cross").lower()
        if td_mode not in {"cross", "isolated", "cash"}:
            td_mode = "cross"
        sz_text = f"{abs(size):.8f}".rstrip("0").rstrip(".")
        logger.info(
            "Protection triggered inst={} side={} dir={} ratio={:.2%} reason={} sz={}",
            inst_id,
            pos_side or "net",
            direction_side,
            profit_ratio,
            reason,
            sz_text,
        )
        try:
            resp = self.okx.place_order(
                inst_id=inst_id,
                td_mode=td_mode,
                side=order_side,
                ord_type="market",
                sz=sz_text,
                pos_side="" if (pos_side or "").lower() == "net" else pos_side,
                reduce_only=True,
            )
            error_info = resp.get("error")
            if error_info:
                data = error_info.get("data") or []
                detail = data[0] if data and isinstance(data, list) else {}
                logger.error(
                    "强制{}失败 inst={} code={} msg={} sCode={} sMsg={}",
                    reason,
                    inst_id,
                    error_info.get("code"),
                    error_info.get("message"),
                    detail.get("sCode"),
                    detail.get("sMsg"),
                )
        except Exception as exc:  # pragma: no cover
            logger.error("强制{}失败 inst={} err={}".format(reason, inst_id, exc))


__all__ = ["ProtectionMonitor", "ProtectionThresholds"]
