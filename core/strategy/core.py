"""策略主编排：融合信号、仓位与保护配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from loguru import logger

from core.models import (
    ProtectionRule,
    ProtectionTarget,
    TradeProtection,
    SignalAction,
    StrategyContext,
    TradeSignal,
)
from .fusion import (
    AnalysisInterpreter,
    AnalysisView,
    ConflictArbitrationConfig,
    LLMInfluenceGuard,
    SignalFusionEngine,
)
from .plugins import build_signal_plugin_manager
from .positioning import PositionSizer
from .signals import ObjectiveSignal, ObjectiveSignalGenerator


@dataclass
class StrategyOutput:
    trade_signal: TradeSignal
    objective_signals: Tuple[ObjectiveSignal, ...]
    analysis_view: AnalysisView
    fusion_notes: Tuple[str, ...]


class Strategy:
    """结合客观指标、分析观点与风控过滤生成交易信号."""

    def __init__(self, settings: Optional[object] = None) -> None:
        plugin_manager = build_signal_plugin_manager(settings)
        self.signal_generator = ObjectiveSignalGenerator(plugin_manager=plugin_manager)
        self.analysis_interpreter = AnalysisInterpreter()
        self.fusion_engine = SignalFusionEngine()
        self.position_sizer = PositionSizer()
        self._llm_influence_guard = self._build_llm_influence_guard(settings)
        self._conflict_arbitration = self._build_conflict_arbitration(settings)

    def generate_signal(
        self,
        context: StrategyContext,
        features: pd.DataFrame,
        analysis_text: str,
        higher_features: Optional[Dict[str, pd.DataFrame]] = None,
        llm_influence_enabled: bool = False,
    ) -> StrategyOutput:
        objective_signals = self.signal_generator.build(features, higher_features)
        analysis_view = self.analysis_interpreter.parse(analysis_text)
        llm_guard = LLMInfluenceGuard(
            enabled=bool(llm_influence_enabled),
            max_confidence_delta=self._llm_influence_guard.max_confidence_delta,
            allow_direction_reverse=self._llm_influence_guard.allow_direction_reverse,
            allow_hold_to_direction=self._llm_influence_guard.allow_hold_to_direction,
        )
        fusion = self.fusion_engine.fuse(
            objective_signals,
            analysis_view,
            llm_guard=llm_guard,
            arbitration_config=self._conflict_arbitration,
        )

        latest = features.iloc[-1]
        liquidity_ok, _liquidity_note = self.signal_generator.liquidity_snapshot(features)
        env_factor, env_note = self.signal_generator.volatility_regime(higher_features)
        notes = list(fusion.notes)
        if env_note:
            notes.append(env_note)
        arbitration_note = next((item for item in fusion.notes if str(item).startswith("[arb]")), "")
        if arbitration_note:
            logger.info("event=strategy_conflict_arbiter note={note}", note=arbitration_note)
        action = fusion.action
        confidence = fusion.confidence
        higher_bias = next((sig for sig in objective_signals if sig.name == "higher_timeframe"), None)
        if (
            higher_bias
            and higher_bias.action != SignalAction.HOLD
            and action != SignalAction.HOLD
            and higher_bias.action != action
            and higher_bias.confidence >= 0.4
        ):
            action = SignalAction.HOLD
            confidence = min(confidence, 0.35)
            notes.append("多周期过滤：高阶趋势与信号方向冲突，跳过本次交易。")
        if action != SignalAction.HOLD and not liquidity_ok:
            action = SignalAction.HOLD
            confidence = min(confidence, 0.3)
        size = 0.0
        trend_bias = higher_bias.action if higher_bias else SignalAction.HOLD
        if action != SignalAction.HOLD:
            size = self.position_sizer.size(
                context=context,
                latest=latest,
                confidence=confidence,
                action=action,
                trend_bias=trend_bias,
                env_factor=env_factor,
            )
        protection: Optional[TradeProtection] = None
        protection_note: Optional[str] = None
        if action != SignalAction.HOLD:
            protection, protection_note = self._build_trade_protection(context, latest, action)
        reason_sections = self._build_reason_sections(
            objective_signals=objective_signals,
            analysis_view=analysis_view,
            context=context,
            fusion_notes=notes,
            analysis_text=analysis_text,
        )
        if protection_note:
            reason_sections.append(protection_note)
        else:
            trade_plan = self.signal_generator.trade_plan(latest, action)
            if trade_plan:
                reason_sections.append(trade_plan)
        trade_signal = TradeSignal(
            action=action,
            confidence=confidence,
            reason="\n\n".join(reason_sections),
            size=size,
            protection=protection,
        )
        logger.debug(
            (
                "Strategy signal inst={inst} timeframe={tf} close={close:.4f} rsi={rsi:.2f} "
                "ema_fast={ema_fast:.6f} ema_slow={ema_slow:.6f} action={action} conf={conf:.2f} size={size:.6f}"
            ).format(
                inst=context.inst_id,
                tf=context.timeframe,
                close=float(latest.get("close", 0.0)),
                rsi=float(latest.get("rsi", 0.0)),
                ema_fast=float(latest.get("ema_fast", 0.0)),
                ema_slow=float(latest.get("ema_slow", 0.0)),
                action=trade_signal.action.value,
                conf=trade_signal.confidence,
                size=trade_signal.size,
            )
        )
        return StrategyOutput(
            trade_signal=trade_signal,
            objective_signals=objective_signals,
            analysis_view=analysis_view,
            fusion_notes=tuple(notes),
        )

    @staticmethod
    def _build_llm_influence_guard(settings: Optional[object]) -> LLMInfluenceGuard:
        llm_settings = getattr(settings, "llm", None) if settings is not None else None
        if llm_settings is None:
            return LLMInfluenceGuard()
        try:
            max_delta = float(getattr(llm_settings, "influence_max_conf_delta", 0.15) or 0.15)
        except (TypeError, ValueError):
            max_delta = 0.15
        return LLMInfluenceGuard(
            enabled=False,
            max_confidence_delta=max(0.0, min(1.0, max_delta)),
            allow_direction_reverse=bool(getattr(llm_settings, "influence_allow_reverse", False)),
            allow_hold_to_direction=bool(getattr(llm_settings, "influence_allow_hold_to_direction", False)),
        )

    @staticmethod
    def _build_conflict_arbitration(settings: Optional[object]) -> ConflictArbitrationConfig:
        strategy_settings = getattr(settings, "strategy", None) if settings is not None else None
        if strategy_settings is None:
            return ConflictArbitrationConfig()
        try:
            same_side_boost = float(getattr(strategy_settings, "strategy_arb_same_side_boost", 0.08) or 0.08)
        except (TypeError, ValueError):
            same_side_boost = 0.08
        try:
            opposite_penalty = float(getattr(strategy_settings, "strategy_arb_opposite_penalty", 0.18) or 0.18)
        except (TypeError, ValueError):
            opposite_penalty = 0.18
        try:
            strong_conflict_ratio = float(
                getattr(strategy_settings, "strategy_arb_strong_conflict_ratio", 0.62) or 0.62
            )
        except (TypeError, ValueError):
            strong_conflict_ratio = 0.62
        try:
            hold_confidence_cap = float(
                getattr(strategy_settings, "strategy_arb_hold_confidence_cap", 0.35) or 0.35
            )
        except (TypeError, ValueError):
            hold_confidence_cap = 0.35
        try:
            min_directional = int(getattr(strategy_settings, "strategy_arb_min_directional_signals", 2) or 2)
        except (TypeError, ValueError):
            min_directional = 2
        return ConflictArbitrationConfig(
            enabled=bool(getattr(strategy_settings, "strategy_arb_enabled", True)),
            same_side_boost=max(0.0, min(0.5, same_side_boost)),
            opposite_side_penalty=max(0.0, min(1.0, opposite_penalty)),
            strong_conflict_ratio=max(0.0, min(1.0, strong_conflict_ratio)),
            hold_confidence_cap=max(0.1, min(1.0, hold_confidence_cap)),
            min_directional_signals=max(1, min(8, min_directional)),
        )

    @staticmethod
    def _build_reason_sections(
        objective_signals: Sequence[ObjectiveSignal],
        analysis_view: AnalysisView,
        context: StrategyContext,
        fusion_notes: Sequence[str],
        analysis_text: str,
    ) -> List[str]:
        sections: List[str] = []
        indicator = next((sig for sig in objective_signals if sig.name == "indicator"), None)
        if indicator:
            sections.append(
                f"指标观点：{indicator.action.value.upper()} (置信 {indicator.confidence:.2f}) - {indicator.note}"
            )
        higher = next((sig for sig in objective_signals if sig.name == "higher_timeframe"), None)
        if higher and higher.note:
            sections.append(f"多周期：{higher.note} (置信 {higher.confidence:.2f})")
        for sig in objective_signals:
            if sig.name in {"indicator", "higher_timeframe"}:
                continue
            label_map = {
                "volume_pressure": "成交量",
                "volatility_breakout": "波动",
                "bull_trend": "趋势",
                "ma_golden_cross": "金叉",
                "shrink_pullback": "回踩",
                "volume_breakout": "放量突破",
                "box_oscillation": "箱体",
                "one_yang_three_yin": "形态",
            }
            label = label_map.get(sig.name, sig.name)
            sections.append(f"{label}：{sig.action.value.upper()} (置信 {sig.confidence:.2f}) - {sig.note}")
        reason_text = analysis_view.reason or analysis_text.strip()
        sections.append(
            f"分析观点：{analysis_view.action.value.upper()} (置信 {analysis_view.confidence:.2f}) - {reason_text}"
        )
        if analysis_view.risk:
            sections.append(f"风险提示：{analysis_view.risk}")
        if analysis_view.time_horizon:
            sections.append(f"适用周期：{analysis_view.time_horizon}")
        if analysis_view.invalid_conditions:
            sections.append(f"失效条件：{analysis_view.invalid_conditions}")
        if context.risk_note:
            sections.append(f"账户提示：{context.risk_note}")
        for note in fusion_notes:
            sections.append(note)
        return sections

    def _build_trade_protection(
        self,
        context: StrategyContext,
        latest: pd.Series,
        action: SignalAction,
    ) -> Tuple[Optional[TradeProtection], Optional[str]]:
        settings = context.protection
        if action == SignalAction.HOLD or not settings:
            return None, None
        tp_active = settings.take_profit.is_active() if settings.take_profit else False
        sl_active = settings.stop_loss.is_active() if settings.stop_loss else False
        if not tp_active and not sl_active:
            return None, None
        close = float(latest.get("close", 0.0) or 0.0)
        atr = float(latest.get("atr", 0.0) or 0.0)
        take_profit = self._build_target(settings.take_profit, close, atr, action, "tp")
        stop_loss = self._build_target(settings.stop_loss, close, atr, action, "sl")
        if not take_profit and not stop_loss:
            return None, None
        protection = TradeProtection(take_profit=take_profit, stop_loss=stop_loss)
        note = self._format_protection_note(protection, close)
        return protection, note

    @staticmethod
    def _build_target(
        rule: ProtectionRule,
        close: float,
        atr: float,
        action: SignalAction,
        kind: str,
    ) -> Optional[ProtectionTarget]:
        if not rule or not rule.is_active():
            return None
        mode = (rule.mode or "").lower()
        value = float(rule.value or 0.0)
        if value <= 0 and mode != "price":
            return None
        direction = 1 if action == SignalAction.BUY else -1
        sign = direction if kind == "tp" else -direction
        trigger_px: Optional[float] = None
        trigger_ratio: Optional[float] = None
        order_type = (rule.order_type or "market").lower()
        trigger_type = rule.trigger_type or "last"
        order_kind = "limit" if order_type == "limit" else "condition"
        if mode == "percent":
            magnitude = abs(value)
            if magnitude <= 0:
                return None
            trigger_ratio = magnitude * sign
            order_type = "market"
            order_kind = "condition"
        elif mode == "atr":
            if atr <= 0:
                return None
            trigger_px = close + sign * atr * value
        elif mode == "price":
            if value <= 0:
                return None
            trigger_px = value
        else:
            return None
        order_px = trigger_px if (trigger_px and order_type == "limit") else None
        return ProtectionTarget(
            trigger_ratio=trigger_ratio,
            trigger_px=trigger_px,
            order_px=order_px,
            order_type=order_type,
            order_kind=order_kind,
            trigger_type=trigger_type,
            mode=mode,
        )

    @staticmethod
    def _format_protection_note(protection: TradeProtection, close: float) -> Optional[str]:
        parts: List[str] = []
        if protection.take_profit:
            parts.append(Strategy._format_target_text("止盈", protection.take_profit, close))
        if protection.stop_loss:
            parts.append(Strategy._format_target_text("止损", protection.stop_loss, close))
        if not parts:
            return None
        return "执行建议：" + "；".join(parts)

    @staticmethod
    def _format_target_text(label: str, target: ProtectionTarget, close: float) -> str:
        mode = target.mode or "-"
        if target.has_ratio():
            pct = target.trigger_ratio * 100 if target.trigger_ratio else 0.0
            return f"{label} {pct:.1f}% ({mode})"
        if target.has_price():
            pct = Strategy._format_pct_diff(target.trigger_px or 0.0, close)
            return f"{label} {(target.trigger_px or 0.0):.6f} ({mode}, {pct})"
        return f"{label} ({mode})"

    @staticmethod
    def _format_pct_diff(target: float, close: float) -> str:
        if close <= 0:
            return "n/a"
        pct = (target / close - 1) * 100
        return f"{pct:+.2f}%"


__all__ = ["Strategy", "StrategyOutput", "AnalysisView", "ObjectiveSignal", "ObjectiveSignalGenerator"]
