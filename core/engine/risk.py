"""多层风控与账户状态建模."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Sequence, Tuple

import pandas as pd

from loguru import logger

from core.models import SignalAction, TradeSignal
from core.strategy import (
    AnalysisView,
    ObjectiveSignal,
    ObjectiveSignalGenerator,
    StrategyOutput,
)


@dataclass
class AccountState:
    equity: float = 0.0
    available: float = 0.0
    pnl: float = 0.0
    under_risk_control: bool = False
    extra: Dict[str, float] | None = None

    @property
    def available_ratio(self) -> float:
        if self.equity <= 0:
            return 0.0
        return max(0.0, min(1.0, self.available / self.equity))


@dataclass
class RiskAssessment:
    trade_signal: TradeSignal
    notes: Tuple[str, ...]
    blocked: bool
    account_state: AccountState


@dataclass
class IntelGateDecision:
    blocked: bool = False
    confidence_cap: Optional[float] = None
    size_ratio: Optional[float] = None
    note: str = ""


@dataclass
class CircuitBreakerState:
    active: bool = False
    reason_code: str = ""
    reason: str = ""
    triggered_at: str = ""
    lock_until: str = ""
    trading_day: str = ""
    daily_pnl: float = 0.0
    daily_loss_limit: float = 0.0
    consecutive_losses: int = 0
    consecutive_limit: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CircuitBreakerState":
        if not isinstance(data, dict):
            return cls()
        return cls(
            active=bool(data.get("active", False)),
            reason_code=str(data.get("reason_code") or ""),
            reason=str(data.get("reason") or ""),
            triggered_at=str(data.get("triggered_at") or ""),
            lock_until=str(data.get("lock_until") or ""),
            trading_day=str(data.get("trading_day") or ""),
            daily_pnl=_safe_float(data.get("daily_pnl")),
            daily_loss_limit=_safe_float(data.get("daily_loss_limit")),
            consecutive_losses=max(0, _safe_int(data.get("consecutive_losses"))),
            consecutive_limit=max(0, _safe_int(data.get("consecutive_limit"))),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RiskManager:
    """账户 / 品种 / 信号三级风控 + 熔断."""

    def __init__(
        self,
        min_available_ratio: float = 0.03,
        max_confidence_when_blocked: float = 0.35,
        daily_loss_limit: float = 0.0,
        daily_loss_limit_pct: float = 0.0,
        consecutive_loss_limit: int = 0,
        consecutive_cooldown_minutes: int = 180,
        state_path: str | Path = "data/risk_circuit_state.json",
        intel_gate_mode: str = "degrade",
        intel_degrade_threshold: float = 0.72,
        intel_block_threshold: float = 0.9,
        intel_degrade_confidence_cap: float = 0.45,
        intel_degrade_size_ratio: float = 0.5,
    ) -> None:
        self.min_available_ratio = min_available_ratio
        self.max_confidence_when_blocked = max_confidence_when_blocked
        self.daily_loss_limit = max(0.0, float(daily_loss_limit or 0.0))
        self.daily_loss_limit_pct = max(0.0, float(daily_loss_limit_pct or 0.0))
        self.consecutive_loss_limit = max(0, int(consecutive_loss_limit or 0))
        self.consecutive_cooldown_minutes = max(1, int(consecutive_cooldown_minutes or 180))
        self.intel_gate_mode = str(intel_gate_mode or "degrade").strip().lower()
        if self.intel_gate_mode not in {"off", "degrade", "block"}:
            self.intel_gate_mode = "degrade"
        self.intel_degrade_threshold = max(0.0, min(1.0, float(intel_degrade_threshold or 0.0)))
        self.intel_block_threshold = max(0.0, min(1.0, float(intel_block_threshold or 0.0)))
        self.intel_degrade_confidence_cap = max(
            0.1,
            min(1.0, float(intel_degrade_confidence_cap or max_confidence_when_blocked)),
        )
        self.intel_degrade_size_ratio = max(0.0, min(1.0, float(intel_degrade_size_ratio or 0.0)))
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self.analytics = ObjectiveSignalGenerator()
        self._state_lock = Lock()
        self._circuit_state = self._load_state()

    def evaluate(
        self,
        account_state: AccountState,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
        strategy_output: StrategyOutput,
        daily_stats: Optional[Dict[str, Any]] = None,
        perf_stats: Optional[Dict[str, Any]] = None,
        market_intel: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        trade_signal = strategy_output.trade_signal
        action = trade_signal.action
        confidence = trade_signal.confidence
        size = trade_signal.size
        notes = []
        blocked = False

        # 账户层风控
        if account_state.under_risk_control:
            blocked = True
            notes.append("交易所风控触发：账户暂不可下单。")
        if account_state.available_ratio < self.min_available_ratio:
            blocked = True
            notes.append(
                f"账户可用资金占比 {account_state.available_ratio:.0%} 低于 {self.min_available_ratio:.0%}，暂停新仓。"
            )

        # 硬风控熔断
        circuit_note = self._evaluate_circuit_breaker(
            account_state=account_state,
            daily_stats=daily_stats,
            perf_stats=perf_stats,
        )
        if circuit_note:
            blocked = True
            notes.append(circuit_note)

        # 情报事件闸门（监管/安全/宏观）
        intel_gate = self._evaluate_intel_gate(market_intel=market_intel)
        if intel_gate.note:
            notes.append(intel_gate.note)
            logger.info(
                "event=intel_gate_applied mode={mode} blocked={blocked} note={note}",
                mode=self.intel_gate_mode,
                blocked=intel_gate.blocked,
                note=intel_gate.note,
            )
        if intel_gate.confidence_cap is not None:
            confidence = min(confidence, intel_gate.confidence_cap)
        if intel_gate.size_ratio is not None:
            size = max(0.0, size * intel_gate.size_ratio)
        if intel_gate.blocked:
            blocked = True

        # 品种层风控
        liquidity_ok, liquidity_note = self.analytics.liquidity_snapshot(features)
        if not liquidity_ok and liquidity_note:
            blocked = True
            notes.append(liquidity_note)
        env_factor, env_note = self.analytics.volatility_regime(higher_features)
        if env_note:
            notes.append(env_note)

        # 信号层风控
        analysis_view = strategy_output.analysis_view
        self._apply_analysis_risk(analysis_view, notes)
        higher_conflict = self._detect_trend_conflict(strategy_output.objective_signals, action)
        if higher_conflict:
            blocked = True
            notes.append(higher_conflict)

        if blocked:
            action = SignalAction.HOLD
            size = 0.0
            confidence = min(confidence, self.max_confidence_when_blocked)

        final_reason = trade_signal.reason
        if notes:
            final_reason = f"{final_reason}\n\n风控提示：{'；'.join(notes)}"
        final_protection = trade_signal.protection if not blocked else None
        final_signal = TradeSignal(
            action=action,
            confidence=confidence,
            reason=final_reason,
            size=size,
            protection=final_protection,
        )
        if blocked:
            logger.debug(
                "RiskManager blocked order action={action} size={size:.6f} reasons={reasons}",
                action=trade_signal.action.value,
                size=trade_signal.size,
                reasons="; ".join(notes),
            )
        return RiskAssessment(
            trade_signal=final_signal,
            notes=tuple(note for note in notes if note),
            blocked=blocked,
            account_state=account_state,
        )

    @staticmethod
    def _apply_analysis_risk(analysis_view: AnalysisView, notes: list[str]) -> None:
        if not analysis_view.risk:
            return
        keywords = ("不确定", "高风险", "谨慎")
        if any(word in analysis_view.risk for word in keywords):
            notes.append(f"分析风险提示：{analysis_view.risk}")

    @staticmethod
    def _detect_trend_conflict(
        objective_signals: Sequence[ObjectiveSignal],
        action: SignalAction,
    ) -> Optional[str]:
        higher = next((sig for sig in objective_signals if sig.name == "higher_timeframe"), None)
        if not higher or higher.action == SignalAction.HOLD or action == SignalAction.HOLD:
            return None
        if higher.action != action and higher.confidence >= 0.4:
            return "多周期风险：高阶趋势与当前信号冲突。"
        return None

    def _evaluate_intel_gate(self, *, market_intel: Optional[Dict[str, Any]]) -> IntelGateDecision:
        if self.intel_gate_mode == "off":
            return IntelGateDecision()
        if not isinstance(market_intel, dict):
            return IntelGateDecision()
        event_tags_raw = market_intel.get("event_tags")
        if not isinstance(event_tags_raw, dict):
            return IntelGateDecision()

        event_tags: Dict[str, float] = {}
        for key, value in event_tags_raw.items():
            tag = str(key or "").strip().lower()
            if not tag:
                continue
            weight = max(0.0, min(1.0, _safe_float(value)))
            if weight <= 0:
                continue
            event_tags[tag] = weight
        if not event_tags:
            return IntelGateDecision()

        risk_score = max(
            max(event_tags.values()),
            max(0.0, min(1.0, _safe_float(market_intel.get("event_risk_score")))),
        )
        labels = ",".join(f"{name}:{weight:.2f}" for name, weight in sorted(event_tags.items()))
        if self.intel_block_threshold > 0 and risk_score >= self.intel_block_threshold:
            note = (
                "情报标签闸门："
                f"{labels} 风险权重 {risk_score:.2f} 达到阻断阈值 {self.intel_block_threshold:.2f}，暂停新仓。"
            )
            return IntelGateDecision(blocked=True, note=note)

        if self.intel_gate_mode == "block" and risk_score >= self.intel_degrade_threshold:
            note = (
                "情报标签闸门："
                f"{labels} 风险权重 {risk_score:.2f} 达到 block 阈值 {self.intel_degrade_threshold:.2f}，暂停新仓。"
            )
            return IntelGateDecision(blocked=True, note=note)

        if self.intel_gate_mode == "degrade" and risk_score >= self.intel_degrade_threshold:
            note = (
                "情报标签闸门："
                f"{labels} 风险权重 {risk_score:.2f} 达到降级阈值 {self.intel_degrade_threshold:.2f}，"
                f"下调置信度≤{self.intel_degrade_confidence_cap:.2f} 且仓位x{self.intel_degrade_size_ratio:.2f}。"
            )
            return IntelGateDecision(
                blocked=False,
                confidence_cap=self.intel_degrade_confidence_cap,
                size_ratio=self.intel_degrade_size_ratio,
                note=note,
            )
        return IntelGateDecision()

    def _evaluate_circuit_breaker(
        self,
        *,
        account_state: AccountState,
        daily_stats: Optional[Dict[str, Any]],
        perf_stats: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        now = self._utcnow()
        today = now.date().isoformat()
        daily_pnl = self._extract_daily_pnl(daily_stats, perf_stats)
        consecutive_losses = self._extract_consecutive_losses(daily_stats, perf_stats)
        daily_loss_limit = self._resolve_daily_loss_limit(account_state)

        with self._state_lock:
            self._refresh_state_locked(now=now, today=today)
            if self._circuit_state.active:
                return self._circuit_state.reason or "风控熔断中，暂停新仓。"

            if daily_loss_limit > 0 and daily_pnl is not None and daily_pnl <= -daily_loss_limit:
                reason = (
                    f"日内亏损 {daily_pnl:+.2f} 已达到阈值 {daily_loss_limit:.2f}，"
                    "触发停机熔断（次日自动恢复）。"
                )
                lock_until = datetime.combine(
                    now.date() + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
                self._circuit_state = CircuitBreakerState(
                    active=True,
                    reason_code="daily_loss",
                    reason=reason,
                    triggered_at=now.isoformat(),
                    lock_until=lock_until.isoformat(),
                    trading_day=today,
                    daily_pnl=float(daily_pnl),
                    daily_loss_limit=float(daily_loss_limit),
                    consecutive_losses=max(0, int(consecutive_losses or 0)),
                    consecutive_limit=self.consecutive_loss_limit,
                )
                self._save_state_locked()
                return reason

            if (
                self.consecutive_loss_limit > 0
                and consecutive_losses is not None
                and consecutive_losses >= self.consecutive_loss_limit
            ):
                reason = (
                    f"连续亏损 {consecutive_losses} 次达到阈值 {self.consecutive_loss_limit}，"
                    f"触发熔断（冷却 {self.consecutive_cooldown_minutes} 分钟）。"
                )
                lock_until = now + timedelta(minutes=self.consecutive_cooldown_minutes)
                self._circuit_state = CircuitBreakerState(
                    active=True,
                    reason_code="consecutive_loss",
                    reason=reason,
                    triggered_at=now.isoformat(),
                    lock_until=lock_until.isoformat(),
                    trading_day=today,
                    daily_pnl=float(daily_pnl or 0.0),
                    daily_loss_limit=float(daily_loss_limit),
                    consecutive_losses=int(consecutive_losses),
                    consecutive_limit=self.consecutive_loss_limit,
                )
                self._save_state_locked()
                return reason
        return None

    def _refresh_state_locked(self, *, now: datetime, today: str) -> None:
        state = self._circuit_state
        if not state.active:
            return
        clear_state = False
        lock_until = _parse_iso_datetime(state.lock_until)

        if state.reason_code == "daily_loss":
            if state.trading_day and state.trading_day != today:
                clear_state = True
            elif lock_until and now >= lock_until:
                clear_state = True
        else:
            if lock_until and now >= lock_until:
                clear_state = True

        if clear_state:
            self._circuit_state = CircuitBreakerState()
            self._save_state_locked()

    def _resolve_daily_loss_limit(self, account_state: AccountState) -> float:
        abs_limit = max(0.0, self.daily_loss_limit)
        pct_limit = 0.0
        if self.daily_loss_limit_pct > 0 and account_state.equity > 0:
            pct_limit = account_state.equity * self.daily_loss_limit_pct
        candidates = [item for item in (abs_limit, pct_limit) if item > 0]
        if not candidates:
            return 0.0
        return min(candidates)

    @staticmethod
    def _extract_daily_pnl(
        daily_stats: Optional[Dict[str, Any]],
        perf_stats: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        for stats in (daily_stats, perf_stats):
            if not isinstance(stats, dict):
                continue
            if stats is perf_stats and int(stats.get("lookback_days", 0) or 0) not in (0, 1):
                continue
            if "total_pnl" in stats:
                return _safe_float(stats.get("total_pnl"))
        return None

    @staticmethod
    def _extract_consecutive_losses(
        daily_stats: Optional[Dict[str, Any]],
        perf_stats: Optional[Dict[str, Any]],
    ) -> Optional[int]:
        for stats in (daily_stats, perf_stats):
            if not isinstance(stats, dict):
                continue
            value = stats.get("consecutive_losses")
            if value is None:
                continue
            return max(0, _safe_int(value))
        return None

    def _load_state(self) -> CircuitBreakerState:
        if not self.state_path.exists():
            return CircuitBreakerState()
        try:
            with self.state_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return CircuitBreakerState()
        return CircuitBreakerState.from_dict(data)

    def _save_state_locked(self) -> None:
        payload = self._circuit_state.to_dict()
        try:
            with self.state_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # pragma: no cover
            logger.warning("写入风控熔断状态失败: {}", exc)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "AccountState",
    "CircuitBreakerState",
    "IntelGateDecision",
    "RiskAssessment",
    "RiskManager",
]
