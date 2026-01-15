"""多层风控与账户状态建模."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import pandas as pd

from loguru import logger

from core.models import SignalAction, TradeSignal
from core.strategy.core import (
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


class RiskManager:
    """账户 / 品种 / 信号三级风控."""

    def __init__(
        self,
        min_available_ratio: float = 0.2,
        max_confidence_when_blocked: float = 0.35,
    ) -> None:
        self.min_available_ratio = min_available_ratio
        self.max_confidence_when_blocked = max_confidence_when_blocked
        self.analytics = ObjectiveSignalGenerator()

    def evaluate(
        self,
        account_state: AccountState,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
        strategy_output: StrategyOutput,
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


__all__ = ["AccountState", "RiskManager", "RiskAssessment"]
