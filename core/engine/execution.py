"""执行计划与下单引擎."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from loguru import logger

from core.client import OKXClient
from core.models import ProtectionTarget, ResolvedTradeProtection, SignalAction, TradeSignal
from core.protection import resolve_trade_protection

MAX_SLIPPAGE_PCT = 0.02
LIMIT_OFFSET_RATIO = 0.001
RATIO_STEP = 0.0001


@dataclass
class InstrumentMeta:
    inst_id: str
    inst_type: str
    lot_size: float
    min_size: float
    contract_value: Optional[float] = None
    contract_currency: Optional[str] = None
    contract_type: Optional[str] = None

    @property
    def is_contract(self) -> bool:
        return self.inst_type.upper() in {"SWAP", "FUTURES"}


@dataclass
class ExecutionPlan:
    inst_id: str
    action: SignalAction
    td_mode: Optional[str]
    pos_side: Optional[str]
    order_type: str
    size: float
    price: Optional[float]
    est_slippage: float
    notes: Tuple[str, ...] = ()
    blocked: bool = False
    block_reason: Optional[str] = None
    protection: Optional[ResolvedTradeProtection] = None
    latest_price: Optional[float] = None
    cl_ord_id: Optional[str] = None


@dataclass
class ExecutionReport:
    plan: ExecutionPlan
    success: bool
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    code: Optional[str] = None


class ExecutionEngine:
    """负责构建执行计划并调用 OKX 下单."""

    def __init__(
        self,
        okx_client: OKXClient,
        max_slippage_pct: float = MAX_SLIPPAGE_PCT,
        pending_timeout_seconds: float = 0.0,
        reconcile_position: bool = True,
    ) -> None:
        self.okx = okx_client
        self.max_slippage_pct = max_slippage_pct
        self.pending_timeout_seconds = max(0.0, float(pending_timeout_seconds or 0.0))
        self.reconcile_position = bool(reconcile_position)
        self._instrument_cache: Dict[str, InstrumentMeta] = {}
        self._loaded_inst_types: Set[str] = set()

    def build_plan(
        self,
        inst_id: str,
        signal: TradeSignal,
        td_mode: Optional[str],
        pos_side: Optional[str],
        latest_price: float,
        atr: float,
        trace_id: Optional[str] = None,
    ) -> ExecutionPlan:
        notes = []
        est_slippage = (atr / latest_price) if latest_price > 0 and atr > 0 else 0.0
        order_type = "market"
        price: Optional[float] = None
        blocked = False
        block_reason: Optional[str] = None
        meta = self._get_instrument_meta(inst_id)
        min_contract_note: Optional[str] = None

        if signal.action == SignalAction.HOLD or signal.size <= 0:
            blocked = True
            block_reason = "无交易动作。"
        else:
            if meta and meta.is_contract:
                contracts = self._convert_size_to_contracts(signal.size, meta, latest_price)
                min_contract = meta.min_size or meta.lot_size or 0.0
                if contracts is not None and min_contract > 0:
                    if contracts < min_contract - 1e-12:
                        min_contract_note = (
                            f"折算张数 {contracts:.6f} 张，低于最小下单 {min_contract:.6f}，已自动抬升。"
                        )
                    else:
                        min_contract_note = (
                            f"折算张数 {contracts:.6f} 张 (最小 {min_contract:.6f})."
                        )
            if signal.confidence >= 0.7 and 0 < est_slippage <= 0.01:
                order_type = "limit"
                offset = max(LIMIT_OFFSET_RATIO, est_slippage * 0.5 or LIMIT_OFFSET_RATIO)
                if signal.action == SignalAction.BUY:
                    price = latest_price * (1 - offset)
                else:
                    price = latest_price * (1 + offset)
                notes.append("低波动 + 高置信 -> 使用限价单改善成交质量。")
            if est_slippage > self.max_slippage_pct:
                blocked = True
                block_reason = (
                    f"预估滑点 {est_slippage:.2%} 超出阈值 {self.max_slippage_pct:.2%}，暂停执行。"
                )

        resolved_protection = None
        if signal.protection and not blocked:
            entry_reference = price if order_type == "limit" and price and price > 0 else latest_price
            resolved_protection = resolve_trade_protection(
                protection=signal.protection,
                action=signal.action,
                entry_price=entry_reference,
                atr=atr,
            )
        if resolved_protection and not blocked:
            notes.append("附带止盈/止损保护。")
        if min_contract_note and not blocked:
            notes.append(min_contract_note)
        cl_ord_id = None
        if signal.action != SignalAction.HOLD and signal.size > 0 and not blocked:
            cl_ord_id = self._build_cl_ord_id(
                inst_id=inst_id,
                action=signal.action,
                trace_id=trace_id,
            )
        return ExecutionPlan(
            inst_id=inst_id,
            action=signal.action,
            td_mode=td_mode,
            pos_side=pos_side,
            order_type=order_type,
            size=max(signal.size, 0.0),
            price=price,
            est_slippage=est_slippage,
            notes=tuple(notes),
            blocked=blocked,
            block_reason=block_reason,
            protection=resolved_protection if not blocked else None,
            latest_price=latest_price,
            cl_ord_id=cl_ord_id,
        )

    def execute(self, plan: ExecutionPlan) -> ExecutionReport:
        if plan.blocked or plan.size <= 0:
            reason = plan.block_reason or "执行计划被拦截。"
            logger.info(f"Execution plan blocked inst={plan.inst_id} reason={reason}")
            return ExecutionReport(plan=plan, success=False, error=reason)
        cl_ord_id = plan.cl_ord_id or self._build_cl_ord_id(
            inst_id=plan.inst_id,
            action=plan.action,
            trace_id=None,
        )
        order_size = self._normalize_order_size(plan.size, plan.inst_id, plan.latest_price)
        price_text = self._format_price(plan.price) if plan.order_type == "limit" else None
        attach_algo_orders = self._build_attach_algo_orders(plan.protection)
        if attach_algo_orders:
            logger.info(
                "Attach algo orders inst_id={} action={} payload={}",
                plan.inst_id,
                plan.action.value,
                attach_algo_orders,
            )
        else:
            logger.info("No protection attached inst_id={} action={}", plan.inst_id, plan.action.value)
        try:
            resp = self.okx.place_order(
                inst_id=plan.inst_id,
                td_mode=plan.td_mode or "cross",
                side="buy" if plan.action == SignalAction.BUY else "sell",
                ord_type=plan.order_type,
                sz=order_size,
                px=price_text,
                cl_ord_id=cl_ord_id,
                pos_side=plan.pos_side,
                attach_algo_ords=attach_algo_orders,
            )
        except Exception as exc:  # pragma: no cover
            logger.exception(f"执行下单异常 inst={plan.inst_id} err={exc}")
            return ExecutionReport(plan=plan, success=False, error=str(exc))
        if resp.get("error"):
            error_info = resp["error"]
            logger.error(
                "执行下单失败 inst={inst} code={code} msg={msg}",
                inst=plan.inst_id,
                code=error_info.get("code"),
                msg=error_info.get("message"),
            )
            return ExecutionReport(
                plan=plan,
                success=False,
                response=resp,
                error=str(error_info.get("message") or ""),
                code=str(error_info.get("code") or ""),
            )
        if self.reconcile_position and plan.action in {SignalAction.BUY, SignalAction.SELL}:
            if not self._has_effective_position(plan.inst_id):
                if self.pending_timeout_seconds > 0:
                    time.sleep(self.pending_timeout_seconds)
                if not self._has_effective_position(plan.inst_id):
                    if self._has_live_pending_order(plan.inst_id, cl_ord_id):
                        logger.info(
                            "Order accepted but still pending inst_id={} cl_ord_id={} ord_type={}",
                            plan.inst_id,
                            cl_ord_id,
                            plan.order_type,
                        )
                        return ExecutionReport(plan=plan, success=True, response=resp)
                    return ExecutionReport(
                        plan=plan,
                        success=False,
                        response=resp,
                        error="订单成交超时：未观察到持仓变化。",
                        code="PENDING_TIMEOUT",
                    )
        return ExecutionReport(plan=plan, success=True, response=resp)

    def _has_effective_position(self, inst_id: str) -> bool:
        if not hasattr(self.okx, "get_positions"):
            return True
        try:
            payload = self.okx.get_positions(inst_type="SWAP")
        except Exception as exc:  # pragma: no cover
            logger.warning("持仓对账失败 inst_id={} err={}", inst_id, exc)
            return True
        data = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return True
        inst_key = str(inst_id or "").upper()
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("instId") or "").upper() != inst_key:
                continue
            try:
                size = abs(float(entry.get("pos") or 0.0))
            except (TypeError, ValueError):
                size = 0.0
            if size > 0:
                return True
        return False

    def has_live_pending_order(self, inst_id: str) -> bool:
        return self._has_live_pending_order(inst_id, None)

    def _has_live_pending_order(self, inst_id: str, cl_ord_id: Optional[str]) -> bool:
        if not hasattr(self.okx, "list_pending_orders"):
            return False
        try:
            entries = self.okx.list_pending_orders(inst_id)
        except Exception as exc:  # pragma: no cover
            logger.warning("查询未成交委托失败 inst_id={} err={}", inst_id, exc)
            return False
        inst_key = str(inst_id or "").upper()
        cl_key = str(cl_ord_id or "").strip()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("instId") or "").upper() != inst_key:
                continue
            state = str(entry.get("state") or "").strip().lower()
            if state and state not in {"live", "partially_filled"}:
                continue
            if cl_key and str(entry.get("clOrdId") or "").strip() != cl_key:
                continue
            return True
        return False

    def _normalize_order_size(self, size: float, inst_id: str, latest_price: Optional[float]) -> str:
        meta = self._get_instrument_meta(inst_id)
        if meta and meta.is_contract:
            contracts = self._convert_size_to_contracts(size, meta, latest_price)
            if contracts is None:
                contracts = size
            lot_size = meta.lot_size or meta.min_size or 1.0
            min_size = meta.min_size or lot_size
            normalized_contracts = self._round_up(contracts, lot_size)
            if normalized_contracts < min_size:
                normalized_contracts = min_size
            return self._format_number(normalized_contracts)
        normalized = max(size, 0.00000001)
        return self._format_number(normalized)

    @staticmethod
    def _round_up(value: float, step: float) -> float:
        if step <= 0:
            return value
        return math.ceil(value / step) * step

    @staticmethod
    def _format_price(price: Optional[float]) -> Optional[str]:
        if price is None or price <= 0:
            return None
        return f"{price:.8f}".rstrip("0").rstrip(".")

    def _format_ratio(self, value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        magnitude = round(abs(value) / RATIO_STEP) * RATIO_STEP
        if magnitude < 1e-9:
            return None
        quantized = magnitude if value > 0 else -magnitude
        return self._format_number(quantized)

    def _format_number(self, value: float) -> str:
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _build_cl_ord_id(inst_id: str, action: SignalAction, trace_id: Optional[str]) -> str:
        inst_token = "".join(ch for ch in inst_id.upper() if ch.isalnum())[:10].lower()
        action_token = action.value[:1].lower() if action.value else "h"
        trace_token = "".join(ch for ch in (trace_id or "").lower() if ch.isalnum())[:8]
        nonce = uuid.uuid4().hex[:10]
        raw = f"cx{action_token}{inst_token}{trace_token}{nonce}"
        return raw[:32]

    def _build_attach_algo_orders(
        self, protection: Optional[ResolvedTradeProtection]
    ) -> Optional[List[Dict[str, str]]]:
        if not protection:
            return None

        def build_order_px(target: ProtectionTarget) -> Optional[str]:
            if (target.order_type or "market").lower() == "market":
                return "-1"
            if target.order_px and target.order_px > 0:
                return self._format_price(target.order_px)
            return self._format_price(target.trigger_px)

        entry: Dict[str, str] = {}
        if protection.take_profit:
            ratio = self._format_ratio(protection.take_profit.trigger_ratio)
            trigger_px = self._format_price(protection.take_profit.trigger_px)
            order_px = build_order_px(protection.take_profit)
            if ratio:
                entry["tpTriggerRatio"] = ratio
                entry["tpTriggerPxType"] = protection.take_profit.trigger_type or "last"
            elif trigger_px:
                entry["tpTriggerPx"] = trigger_px
                entry["tpTriggerPxType"] = protection.take_profit.trigger_type or "last"
            if order_px:
                entry["tpOrdPx"] = order_px
            entry["tpOrdKind"] = protection.take_profit.order_kind or "condition"
        if protection.stop_loss:
            ratio = self._format_ratio(protection.stop_loss.trigger_ratio)
            trigger_px = self._format_price(protection.stop_loss.trigger_px)
            order_px = build_order_px(protection.stop_loss)
            if ratio:
                entry["slTriggerRatio"] = ratio
                entry["slTriggerPxType"] = protection.stop_loss.trigger_type or "last"
            elif trigger_px:
                entry["slTriggerPx"] = trigger_px
                entry["slTriggerPxType"] = protection.stop_loss.trigger_type or "last"
            if order_px:
                entry["slOrdPx"] = order_px
            entry["slOrdKind"] = protection.stop_loss.order_kind or "condition"
        if not entry:
            return None
        return [entry]

    def _get_instrument_meta(self, inst_id: str) -> Optional[InstrumentMeta]:
        inst_key = inst_id.upper()
        if inst_key in self._instrument_cache:
            return self._instrument_cache[inst_key]
        inst_type = self._infer_inst_type(inst_key)
        if inst_type not in self._loaded_inst_types:
            try:
                resp = self.okx.instruments(inst_type=inst_type)
            except Exception as exc:  # pragma: no cover
                logger.warning(f"获取合约规格失败 inst={inst_id} err={exc}")
                self._loaded_inst_types.add(inst_type)
            else:
                data = resp.get("data") or []
                for entry in data:
                    meta = self._build_instrument_meta(entry)
                    if meta:
                        self._instrument_cache[meta.inst_id.upper()] = meta
                self._loaded_inst_types.add(inst_type)
        return self._instrument_cache.get(inst_key)

    @staticmethod
    def _infer_inst_type(inst_id: str) -> str:
        inst = inst_id.upper()
        if inst.endswith("-SWAP"):
            return "SWAP"
        if inst.endswith("-FUTURES"):
            return "FUTURES"
        if inst.endswith("-OPTION"):
            return "OPTION"
        return "SPOT"

    @staticmethod
    def _build_instrument_meta(entry: Dict[str, Any]) -> Optional[InstrumentMeta]:
        inst_id = entry.get("instId")
        inst_type = entry.get("instType")
        if not inst_id or not inst_type:
            return None
        lot_size = _safe_float(entry.get("lotSz"))
        min_size = _safe_float(entry.get("minSz"))
        contract_value = _safe_float(entry.get("ctVal"))
        return InstrumentMeta(
            inst_id=str(inst_id),
            inst_type=str(inst_type).upper(),
            lot_size=lot_size if lot_size and lot_size > 0 else 1.0,
            min_size=min_size if min_size and min_size > 0 else (lot_size if lot_size and lot_size > 0 else 1.0),
            contract_value=contract_value,
            contract_currency=entry.get("ctValCcy"),
            contract_type=entry.get("ctType"),
        )

    def get_min_underlying_size(self, inst_id: str, latest_price: Optional[float]) -> Optional[float]:
        meta = self._get_instrument_meta(inst_id)
        if not meta:
            return None
        min_contracts = meta.min_size or meta.lot_size
        if not min_contracts or min_contracts <= 0:
            return None
        return self._contracts_to_underlying(min_contracts, meta, latest_price)

    def _convert_size_to_contracts(
        self,
        size: float,
        meta: InstrumentMeta,
        latest_price: Optional[float],
    ) -> Optional[float]:
        if size <= 0:
            return 0.0
        if not meta.is_contract or not meta.contract_value or meta.contract_value <= 0:
            return size
        ct_type = (meta.contract_type or "").lower()
        ct_ccy = (meta.contract_currency or "").upper()
        if ct_type == "linear" or ct_ccy not in {"USD", "USDT", "USDC"}:
            return size / meta.contract_value
        if latest_price and latest_price > 0:
            notional = size * latest_price
            return notional / meta.contract_value
        return None

    def _contracts_to_underlying(
        self,
        contracts: float,
        meta: InstrumentMeta,
        latest_price: Optional[float],
    ) -> Optional[float]:
        if contracts <= 0:
            return 0.0
        if not meta.is_contract or not meta.contract_value or meta.contract_value <= 0:
            return contracts
        ct_type = (meta.contract_type or "").lower()
        ct_ccy = (meta.contract_currency or "").upper()
        if ct_type == "linear" or ct_ccy not in {"USD", "USDT", "USDC"}:
            return contracts * meta.contract_value
        if latest_price and latest_price > 0:
            return contracts * meta.contract_value / latest_price
        return None



def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ExecutionEngine", "ExecutionPlan", "ExecutionReport"]
