"""Exchange-side OCO reconciliation for a single protection order per live position."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from core.client import OKXClient
from core.engine.protection import ProtectionThresholds


@dataclass
class DesiredOcoOrder:
    inst_id: str
    ord_type: str
    td_mode: str
    side: str
    pos_side: str
    tp_trigger_px: Optional[str]
    tp_order_px: Optional[str]
    tp_trigger_px_type: str
    sl_trigger_px: Optional[str]
    sl_order_px: Optional[str]
    sl_trigger_px_type: str
    size: Optional[str]
    close_fraction: Optional[str]
    reduce_only: bool = True


class ProtectionOrderManager:
    """Keeps exactly one exchange OCO protection order per live position."""

    def __init__(
        self,
        okx_client: OKXClient,
        thresholds: ProtectionThresholds,
        default_td_mode: str = "cross",
        interval_seconds: float = 15.0,
        per_inst_thresholds: Optional[Dict[str, ProtectionThresholds | Dict[str, Any]]] = None,
    ) -> None:
        self.okx = okx_client
        self.thresholds = thresholds
        self.default_td_mode = (default_td_mode or "cross").lower() or "cross"
        self.interval_seconds = max(5.0, float(interval_seconds or 15.0))
        self.per_inst_thresholds: Dict[str, ProtectionThresholds] = {}
        if isinstance(per_inst_thresholds, dict):
            for inst_id, node in per_inst_thresholds.items():
                normalized = self._normalize_threshold(node)
                if not normalized:
                    continue
                key = str(inst_id or "").strip().upper()
                if key:
                    self.per_inst_thresholds[key] = normalized
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="protection-order-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.enforce()
            self._stop_event.wait(self.interval_seconds)

    def set_inst_threshold(self, inst_id: str, threshold: ProtectionThresholds | Dict[str, Any]) -> None:
        key = str(inst_id or "").strip().upper()
        if not key:
            return
        normalized = self._normalize_threshold(threshold)
        if not normalized:
            return
        self.per_inst_thresholds[key] = normalized

    def enforce(self) -> None:
        try:
            positions_resp = self.okx.get_positions(inst_type="SWAP")
        except Exception as exc:  # pragma: no cover
            logger.warning("查询持仓失败，无法同步 OCO 保护：{}", exc)
            return
        positions = positions_resp.get("data") or []
        try:
            algo_orders = self.okx.list_algo_orders(ord_type="oco") + self.okx.list_algo_orders(ord_type="conditional")
        except Exception as exc:  # pragma: no cover
            logger.warning("查询保护策略单失败 err={}", exc)
            return

        desired_by_key: Dict[Tuple[str, str], DesiredOcoOrder] = {}
        for entry in positions:
            desired = self._build_desired_order(entry)
            if desired is None:
                continue
            desired_by_key[(desired.inst_id, desired.pos_side)] = desired

        existing_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for entry in algo_orders:
            if not isinstance(entry, dict):
                continue
            state = str(entry.get("state") or "").strip().lower()
            if state and state not in {"live", "partially_filled"}:
                continue
            inst_id = str(entry.get("instId") or "").strip().upper()
            if not inst_id:
                continue
            pos_side = self._normalize_pos_side(entry.get("posSide"), entry.get("side"))
            existing_by_key.setdefault((inst_id, pos_side), []).append(entry)

        for key in sorted(set(desired_by_key) | set(existing_by_key)):
            desired = desired_by_key.get(key)
            existing = existing_by_key.get(key, [])
            self._reconcile(key, desired, existing)

    def _reconcile(
        self,
        key: Tuple[str, str],
        desired: Optional[DesiredOcoOrder],
        existing: List[Dict[str, Any]],
    ) -> None:
        inst_id, _ = key
        if desired is None:
            if existing:
                self.okx.cancel_algo_orders(existing)
            return
        if not existing:
            self._place_order(desired)
            return
        if len(existing) > 1:
            self.okx.cancel_algo_orders(existing)
            self._place_order(desired)
            return
        current = existing[0]
        if self._algo_matches(current, desired):
            return
        if self._can_amend(current, desired):
            self._amend_order(current, desired)
            return
        self.okx.cancel_algo_orders(existing)
        self._place_order(desired)

    def _place_order(self, desired: DesiredOcoOrder) -> None:
        logger.info(
            "同步保护单：创建 inst={} ord_type={} pos_side={} tp={} sl={}",
            desired.inst_id,
            desired.ord_type,
            desired.pos_side,
            desired.tp_trigger_px or "-",
            desired.sl_trigger_px or "-",
        )
        payload = {
            "inst_id": desired.inst_id,
            "td_mode": desired.td_mode,
            "side": desired.side,
            "ord_type": desired.ord_type,
            "pos_side": desired.pos_side,
            "reduce_only": desired.reduce_only,
        }
        if desired.tp_trigger_px:
            payload["tp_trigger_px"] = desired.tp_trigger_px
            payload["tp_order_px"] = desired.tp_order_px
            payload["tp_trigger_px_type"] = desired.tp_trigger_px_type
        if desired.sl_trigger_px:
            payload["sl_trigger_px"] = desired.sl_trigger_px
            payload["sl_order_px"] = desired.sl_order_px
            payload["sl_trigger_px_type"] = desired.sl_trigger_px_type
        if desired.size:
            payload["size"] = desired.size
        if desired.close_fraction:
            payload["close_fraction"] = desired.close_fraction
        self.okx.place_algo_order(**payload)

    def _amend_order(self, current: Dict[str, Any], desired: DesiredOcoOrder) -> None:
        algo_id = str(current.get("algoId") or "").strip()
        if not algo_id:
            self.okx.cancel_algo_orders([current])
            self._place_order(desired)
            return
        logger.info(
            "同步保护单：修改 inst={} algo_id={} tp={} sl={}",
            desired.inst_id,
            algo_id,
            desired.tp_trigger_px or "-",
            desired.sl_trigger_px or "-",
        )
        payload = {
            "inst_id": desired.inst_id,
            "algo_id": algo_id,
        }
        if desired.size:
            payload["new_size"] = desired.size
        if desired.tp_trigger_px:
            payload["new_tp_trigger_px"] = desired.tp_trigger_px
            payload["new_tp_order_px"] = desired.tp_order_px
            payload["new_tp_trigger_px_type"] = desired.tp_trigger_px_type
        if desired.sl_trigger_px:
            payload["new_sl_trigger_px"] = desired.sl_trigger_px
            payload["new_sl_order_px"] = desired.sl_order_px
            payload["new_sl_trigger_px_type"] = desired.sl_trigger_px_type
        self.okx.amend_algo_order(**payload)

    def _build_desired_order(self, entry: Dict[str, Any]) -> Optional[DesiredOcoOrder]:
        if not isinstance(entry, dict):
            return None
        inst_id = str(entry.get("instId") or "").strip().upper()
        if not inst_id:
            return None
        pos_side = self._normalize_pos_side(entry.get("posSide"), entry.get("side"))
        raw_pos = self._safe_float(entry.get("pos"))
        if raw_pos is None or abs(raw_pos) <= 0:
            return None
        avg_px = self._safe_float(entry.get("avgPx"))
        if avg_px is None or avg_px <= 0:
            return None
        thresholds = self._resolve_threshold(inst_id)
        if thresholds.take_profit_upl_ratio <= 0 and thresholds.stop_loss_upl_ratio <= 0:
            return None
        direction = self._position_direction(pos_side, raw_pos)
        if direction is None:
            return None
        leverage = self._resolve_leverage(entry)
        side = "sell" if direction == "long" else "buy"
        td_mode = str(entry.get("mgnMode") or entry.get("marginMode") or self.default_td_mode).strip().lower()
        if td_mode not in {"cross", "isolated", "cash"}:
            td_mode = self.default_td_mode

        tp_trigger_px = None
        sl_trigger_px = None
        if thresholds.take_profit_upl_ratio > 0:
            move = thresholds.take_profit_upl_ratio / leverage
            factor = 1 + move if direction == "long" else 1 - move
            tp_trigger_px = self._format_price(avg_px * factor)
        if thresholds.stop_loss_upl_ratio > 0:
            move = thresholds.stop_loss_upl_ratio / leverage
            factor = 1 - move if direction == "long" else 1 + move
            sl_trigger_px = self._format_price(avg_px * factor)
        if not tp_trigger_px and not sl_trigger_px:
            return None

        normalized_pos_side = "net" if pos_side == "net" else pos_side
        size = None if normalized_pos_side == "net" else self._format_size(abs(raw_pos))
        close_fraction = "1" if normalized_pos_side == "net" else None
        ord_type = "oco" if tp_trigger_px and sl_trigger_px else "conditional"
        return DesiredOcoOrder(
            inst_id=inst_id,
            ord_type=ord_type,
            td_mode=td_mode,
            side=side,
            pos_side=normalized_pos_side,
            tp_trigger_px=tp_trigger_px,
            tp_order_px="-1" if tp_trigger_px else None,
            tp_trigger_px_type="last",
            sl_trigger_px=sl_trigger_px,
            sl_order_px="-1" if sl_trigger_px else None,
            sl_trigger_px_type="last",
            size=size,
            close_fraction=close_fraction,
        )

    def _algo_matches(self, current: Dict[str, Any], desired: DesiredOcoOrder) -> bool:
        if str(current.get("ordType") or "").strip().lower() != desired.ord_type:
            return False
        if str(current.get("side") or "").strip().lower() != desired.side:
            return False
        if self._normalize_pos_side(current.get("posSide"), current.get("side")) != desired.pos_side:
            return False
        if str(current.get("tdMode") or "").strip().lower() not in {"", desired.td_mode}:
            return False
        if self._normalize_decimal(current.get("tpTriggerPx")) != self._normalize_decimal(desired.tp_trigger_px):
            return False
        if self._normalize_decimal(current.get("slTriggerPx")) != self._normalize_decimal(desired.sl_trigger_px):
            return False
        if desired.close_fraction is not None:
            return str(current.get("closeFraction") or "").strip() == desired.close_fraction
        return self._normalize_decimal(current.get("sz")) == self._normalize_decimal(desired.size)

    @staticmethod
    def _can_amend(current: Dict[str, Any], desired: DesiredOcoOrder) -> bool:
        if str(current.get("ordType") or "").strip().lower() != desired.ord_type:
            return False
        if str(current.get("side") or "").strip().lower() != desired.side:
            return False
        if ProtectionOrderManager._normalize_pos_side(current.get("posSide"), current.get("side")) != desired.pos_side:
            return False
        if desired.close_fraction is not None:
            return str(current.get("closeFraction") or "").strip() == desired.close_fraction
        return True

    def _resolve_threshold(self, inst_id: str) -> ProtectionThresholds:
        key = str(inst_id or "").strip().upper()
        if key and key in self.per_inst_thresholds:
            return self.per_inst_thresholds[key]
        return self.thresholds

    @staticmethod
    def _normalize_threshold(node: ProtectionThresholds | Dict[str, Any]) -> Optional[ProtectionThresholds]:
        if isinstance(node, ProtectionThresholds):
            return ProtectionThresholds(
                take_profit_upl_ratio=max(0.0, float(node.take_profit_upl_ratio or 0.0)),
                stop_loss_upl_ratio=max(0.0, float(node.stop_loss_upl_ratio or 0.0)),
            )
        if not isinstance(node, dict):
            return None
        if "take_profit_upl_ratio" not in node and "stop_loss_upl_ratio" not in node:
            return None
        tp = max(0.0, float(node.get("take_profit_upl_ratio") or 0.0))
        sl = max(0.0, float(node.get("stop_loss_upl_ratio") or 0.0))
        return ProtectionThresholds(take_profit_upl_ratio=tp, stop_loss_upl_ratio=sl)

    @staticmethod
    def _normalize_pos_side(pos_side: object, side_hint: object = None) -> str:
        normalized = str(pos_side or "").strip().lower()
        if normalized in {"long", "short", "net"}:
            return normalized
        side = str(side_hint or "").strip().lower()
        if side == "buy":
            return "short"
        if side == "sell":
            return "long"
        return "net"

    @staticmethod
    def _position_direction(pos_side: str, raw_pos: float) -> Optional[str]:
        if pos_side in {"long", "short"}:
            return pos_side
        if raw_pos > 0:
            return "long"
        if raw_pos < 0:
            return "short"
        return None

    @staticmethod
    def _format_price(value: float) -> Optional[str]:
        if value <= 0:
            return None
        return f"{value:.8f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_size(value: float) -> Optional[str]:
        if value <= 0:
            return None
        return f"{value:.8f}".rstrip("0").rstrip(".")

    @staticmethod
    def _safe_float(value: object) -> Optional[float]:
        try:
            if value in ("", None):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_leverage(self, entry: Dict[str, Any]) -> float:
        leverage = entry.get("lever")
        try:
            return max(1.0, float(leverage or 1.0))
        except (TypeError, ValueError):
            logger.warning(
                "保护单同步杠杆解析失败 inst={} lever={}",
                entry.get("instId"),
                leverage,
            )
            return 1.0

    @staticmethod
    def _normalize_decimal(value: object) -> str:
        try:
            if value in ("", None):
                return ""
            return f"{float(value):.8f}"
        except (TypeError, ValueError):
            return str(value or "")


__all__ = ["ProtectionOrderManager", "DesiredOcoOrder"]
