"""分析解析与信号融合。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple, List

from core.models import SignalAction
from .signals import ObjectiveSignal, REVERSAL_ONLY_INDICATOR_NOTES
from .plugins import CONFIRMATION_ONLY_PLUGINS


ACTION_KEYWORDS = {
    SignalAction.BUY: ["buy", "long", "做多", "买入", "多单", "看涨", "偏多", "多头"],
    SignalAction.SELL: ["sell", "short", "做空", "卖出", "空单", "看跌", "偏空", "空头"],
}


@dataclass
class AnalysisView:
    """分析视图."""

    action: SignalAction
    confidence: float
    reason: str = ""
    risk: str = ""
    time_horizon: str = ""
    invalid_conditions: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class LLMInfluenceGuard:
    enabled: bool = False
    max_confidence_delta: float = 0.15
    allow_direction_reverse: bool = False
    allow_hold_to_direction: bool = False


@dataclass(frozen=True)
class ConflictArbitrationConfig:
    enabled: bool = True
    same_side_boost: float = 0.08
    opposite_side_penalty: float = 0.18
    strong_conflict_ratio: float = 0.62
    hold_confidence_cap: float = 0.35
    min_directional_signals: int = 2


class AnalysisInterpreter:
    """负责解析与校验分析结构."""

    def parse(self, text: str) -> AnalysisView:
        structured = self._extract_structured_json(text)
        if structured:
            action_text = str(structured.get("action", "")).strip()
            action = self._normalize_action(action_text)
            confidence = self._sanitize_confidence(structured.get("confidence"))
            reason = structured.get("reason", "") or ""
            risk = structured.get("risk", "") or ""
            horizon = structured.get("time_horizon") or structured.get("horizon") or ""
            invalid = (
                structured.get("invalid_conditions")
                or structured.get("invalid_condition")
                or structured.get("invalid")
                or ""
            )
            return AnalysisView(
                action=action,
                confidence=confidence,
                reason=str(reason).strip(),
                risk=str(risk).strip(),
                time_horizon=str(horizon).strip(),
                invalid_conditions=str(invalid).strip(),
                raw_text=text.strip(),
            )
        lowered = text.lower()
        for action, keywords in ACTION_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                conf = self._extract_confidence(text)
                return AnalysisView(action=action, confidence=conf, reason=text.strip(), raw_text=text.strip())
        conf = self._extract_confidence(text)
        return AnalysisView(action=SignalAction.HOLD, confidence=conf, reason=text.strip(), raw_text=text.strip())

    def from_market_analysis(self, analysis: Any) -> AnalysisView:
        trend = getattr(analysis, "trend", None)
        momentum = getattr(analysis, "momentum", None)
        risk = getattr(analysis, "risk", None)
        levels = getattr(analysis, "levels", None)

        trend_direction = str(getattr(trend, "direction", "range") or "range")
        trend_strength = max(0.0, min(1.0, float(getattr(trend, "strength", 0.0) or 0.0)))
        trend_label = str(getattr(trend, "label", "") or "")
        momentum_score = max(-1.0, min(1.0, float(getattr(momentum, "score", 0.0) or 0.0)))
        momentum_label = str(getattr(momentum, "label", "neutral") or "neutral")

        if trend_direction == "bullish" and momentum_score > 0.12:
            action = SignalAction.BUY
        elif trend_direction == "bearish" and momentum_score < -0.12:
            action = SignalAction.SELL
        else:
            action = SignalAction.HOLD

        confidence = trend_strength * 0.65 + abs(momentum_score) * 0.35
        if action == SignalAction.HOLD:
            confidence = min(0.45, confidence)
        confidence = max(0.1, min(1.0, confidence))

        detail_parts = []
        if trend_label:
            detail_parts.append(f"趋势={trend_label}")
        detail_parts.append(f"动量={momentum_label}({momentum_score:+.2f})")
        nearest_support = getattr(levels, "nearest_support", None)
        nearest_resistance = getattr(levels, "nearest_resistance", None)
        if nearest_support is not None:
            detail_parts.append(f"最近支撑={float(nearest_support):.4f}")
        if nearest_resistance is not None:
            detail_parts.append(f"最近阻力={float(nearest_resistance):.4f}")
        reason = "结构化分析：" + "；".join(detail_parts)

        risk_text = ""
        risk_factors = list(getattr(risk, "factors", []) or [])
        if risk_factors:
            risk_text = "；".join(str(item) for item in risk_factors)

        return AnalysisView(
            action=action,
            confidence=confidence,
            reason=reason,
            risk=risk_text,
            raw_text=reason,
        )

    @classmethod
    def has_structured_payload(cls, text: str) -> bool:
        return cls._extract_structured_json(text.strip()) is not None

    @staticmethod
    def _extract_structured_json(text: str) -> Optional[dict]:
        cleaned = text.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                return None
        match = re.search(r"(\{[\s\S]*\})", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _extract_confidence(text: str) -> float:
        numbers = re.findall(r"0\.\d+|1\.0", text)
        if numbers:
            try:
                value = max(float(num) for num in numbers)
                return max(0.1, min(1.0, value))
            except ValueError:
                pass
        for keyword, value in {
            "高置信": 0.8,
            "strong": 0.8,
            "谨慎": 0.3,
            "low": 0.3,
        }.items():
            if keyword in text.lower():
                return value
        return 0.5

    @staticmethod
    def _sanitize_confidence(value: Optional[float]) -> float:
        if value is None:
            return 0.5
        try:
            return max(0.1, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.5

    @staticmethod
    def _normalize_action(value: str) -> SignalAction:
        lowered = value.lower()
        if lowered in ("buy", "long", "做多", "买入", "多", "看涨"):
            return SignalAction.BUY
        if lowered in ("sell", "short", "做空", "卖出", "空", "看跌"):
            return SignalAction.SELL
        return SignalAction.HOLD


@dataclass
class FusionResult:
    action: SignalAction
    confidence: float
    notes: Tuple[str, ...]


class SignalFusionEngine:
    """融合客观指标与分析观点."""

    SUPPORTIVE_NAMES = {
        "volume_pressure",
        "volatility_breakout",
        "bull_trend",
        "ma_golden_cross",
        "shrink_pullback",
        "volume_breakout",
        "box_oscillation",
        "one_yang_three_yin",
    }

    def fuse(
        self,
        objective_signals: Sequence[ObjectiveSignal],
        analysis_view: AnalysisView,
        llm_guard: Optional[LLMInfluenceGuard] = None,
        arbitration_config: Optional[ConflictArbitrationConfig] = None,
        seeded_action: SignalAction = SignalAction.HOLD,
        seeded_confidence: float = 0.4,
        allow_support_promotion: bool = False,
    ) -> FusionResult:
        indicator = self._get_signal(objective_signals, "indicator")
        higher_tf = self._get_signal(objective_signals, "higher_timeframe")
        base_action = seeded_action
        base_conf = float(seeded_confidence or 0.0) if seeded_confidence is not None else 0.0
        notes: List[str] = []
        if indicator and indicator.action == seeded_action and indicator.note not in REVERSAL_ONLY_INDICATOR_NOTES:
            base_conf = max(base_conf, float(indicator.confidence or 0.0))
        if higher_tf and higher_tf.action != SignalAction.HOLD:
            if higher_tf.action == base_action:
                base_conf = min(1.0, base_conf + 0.15 * max(0.5, higher_tf.confidence))
            else:
                base_conf = max(0.2, base_conf - 0.2 * max(0.5, higher_tf.confidence))
            notes.append(f"多周期：{higher_tf.note}")
        for support in objective_signals:
            if support.name not in self.SUPPORTIVE_NAMES or support.action == SignalAction.HOLD:
                continue
            if support.name in CONFIRMATION_ONLY_PLUGINS:
                continue
            if base_action == SignalAction.HOLD and not allow_support_promotion:
                continue
            label = {
                "volume_pressure": "成交量",
                "volatility_breakout": "波动",
                "bull_trend": "趋势",
                "ma_golden_cross": "金叉",
                "shrink_pullback": "回踩",
                "volume_breakout": "放量突破",
                "box_oscillation": "箱体",
                "one_yang_three_yin": "形态",
            }.get(support.name, support.name)
            if base_action == SignalAction.HOLD:
                base_action = support.action
                base_conf = support.confidence
            elif support.action == base_action:
                base_conf = min(1.0, base_conf + 0.1 * max(0.3, support.confidence))
            else:
                base_conf = max(0.2, base_conf - 0.1 * max(0.3, support.confidence))
            notes.append(f"{label}：{support.note}")
        action, confidence, guard_note = self._combine_actions(
            base_action,
            base_conf,
            analysis_view.action,
            analysis_view.confidence,
            llm_guard=llm_guard,
        )
        if guard_note:
            notes.append(guard_note)
        action, confidence, arbitration_note = self._apply_conflict_arbitration(
            objective_signals=objective_signals,
            action=action,
            confidence=confidence,
            config=arbitration_config or ConflictArbitrationConfig(),
        )
        if arbitration_note:
            notes.append(arbitration_note)
        return FusionResult(action=action, confidence=confidence, notes=tuple(note for note in notes if note))

    @staticmethod
    def _get_signal(signals: Sequence[ObjectiveSignal], name: str) -> Optional[ObjectiveSignal]:
        for signal in signals:
            if signal.name == name:
                return signal
        return None

    @staticmethod
    def _combine_actions(
        indicator_action: SignalAction,
        indicator_conf: float,
        llm_action: SignalAction,
        llm_conf: float,
        llm_guard: Optional[LLMInfluenceGuard] = None,
    ) -> Tuple[SignalAction, float, Optional[str]]:
        guard_note: Optional[str] = None
        force_hold = False
        if llm_guard and llm_guard.enabled:
            llm_action, llm_conf, guard_note, force_hold = SignalFusionEngine._apply_llm_guard(
                indicator_action=indicator_action,
                indicator_conf=indicator_conf,
                llm_action=llm_action,
                llm_conf=llm_conf,
                guard=llm_guard,
            )
        if force_hold:
            return SignalAction.HOLD, max(0.2, llm_conf), guard_note
        if indicator_action == llm_action:
            return indicator_action, min(1.0, max(indicator_conf, llm_conf)), guard_note
        if llm_action == SignalAction.HOLD:
            return indicator_action, max(0.2, indicator_conf * 0.9), guard_note
        if indicator_action == SignalAction.HOLD:
            return llm_action, max(0.2, llm_conf * 0.9), guard_note
        if indicator_conf > llm_conf + 0.15:
            return indicator_action, max(0.2, indicator_conf - 0.1), guard_note
        if llm_conf > indicator_conf + 0.15:
            return llm_action, max(0.2, llm_conf - 0.1), guard_note
        return SignalAction.HOLD, min(indicator_conf, llm_conf) * 0.5, guard_note

    @staticmethod
    def _apply_llm_guard(
        *,
        indicator_action: SignalAction,
        indicator_conf: float,
        llm_action: SignalAction,
        llm_conf: float,
        guard: LLMInfluenceGuard,
    ) -> Tuple[SignalAction, float, Optional[str], bool]:
        delta = max(0.0, float(guard.max_confidence_delta or 0.0))
        capped_llm_conf = max(0.1, min(1.0, min(llm_conf, indicator_conf + delta)))

        if (
            indicator_action in {SignalAction.BUY, SignalAction.SELL}
            and llm_action in {SignalAction.BUY, SignalAction.SELL}
            and indicator_action != llm_action
            and not guard.allow_direction_reverse
        ):
            blocked_conf = min(capped_llm_conf, indicator_conf) * 0.5
            return (
                SignalAction.HOLD,
                max(0.2, blocked_conf),
                "LLM 影响上限：禁止直接反转方向，已降级为 HOLD。",
                True,
            )

        if (
            indicator_action == SignalAction.HOLD
            and llm_action in {SignalAction.BUY, SignalAction.SELL}
            and not guard.allow_hold_to_direction
        ):
            return (
                SignalAction.HOLD,
                max(0.2, indicator_conf),
                "LLM 影响上限：不允许从 HOLD 直接提升为方向信号。",
                True,
            )

        if llm_conf > capped_llm_conf + 1e-12:
            return llm_action, capped_llm_conf, "LLM 影响上限：已限制置信度增幅。", False
        return llm_action, capped_llm_conf, None, False

    @staticmethod
    def _apply_conflict_arbitration(
        *,
        objective_signals: Sequence[ObjectiveSignal],
        action: SignalAction,
        confidence: float,
        config: ConflictArbitrationConfig,
    ) -> Tuple[SignalAction, float, Optional[str]]:
        if not config.enabled:
            return action, confidence, None
        directional: List[ObjectiveSignal] = []
        for sig in objective_signals:
            if sig.name == "higher_timeframe":
                continue
            if sig.name in CONFIRMATION_ONLY_PLUGINS:
                continue
            if sig.name == "indicator" and sig.note in REVERSAL_ONLY_INDICATOR_NOTES:
                continue
            if sig.action not in {SignalAction.BUY, SignalAction.SELL}:
                continue
            directional.append(sig)
        if len(directional) < max(1, int(config.min_directional_signals or 1)):
            return action, confidence, None
        buy_score = sum(max(0.0, float(sig.confidence or 0.0)) for sig in directional if sig.action == SignalAction.BUY)
        sell_score = sum(max(0.0, float(sig.confidence or 0.0)) for sig in directional if sig.action == SignalAction.SELL)
        total = buy_score + sell_score
        if total <= 1e-12:
            return action, confidence, None

        dominant_action = SignalAction.BUY if buy_score >= sell_score else SignalAction.SELL
        dominant_score = buy_score if dominant_action == SignalAction.BUY else sell_score
        opposite_score = sell_score if dominant_action == SignalAction.BUY else buy_score
        conflict_ratio = opposite_score / total if total > 0 else 0.0

        new_action = action
        new_confidence = max(0.1, min(1.0, float(confidence or 0.0)))
        decision = "none"

        if action in {SignalAction.BUY, SignalAction.SELL}:
            align_score = buy_score if action == SignalAction.BUY else sell_score
            oppose_score = sell_score if action == SignalAction.BUY else buy_score
            if align_score > 0 and oppose_score <= 0:
                boost = max(0.0, float(config.same_side_boost or 0.0))
                new_confidence = min(1.0, new_confidence + boost * min(1.0, align_score))
                decision = "boost"
            elif oppose_score > 0:
                penalty = max(0.0, float(config.opposite_side_penalty or 0.0))
                local_conflict = oppose_score / max(1e-9, align_score + oppose_score)
                new_confidence = max(0.1, new_confidence - penalty * local_conflict)
                decision = "penalty"
                threshold = max(0.0, min(1.0, float(config.strong_conflict_ratio or 0.0)))
                if local_conflict >= threshold and dominate_side(align_score, oppose_score) == "oppose":
                    new_action = SignalAction.HOLD
                    cap = max(0.1, min(1.0, float(config.hold_confidence_cap or 0.35)))
                    new_confidence = min(new_confidence, cap)
                    decision = "hold"

        note = (
            "[arb] "
            f"decision={decision} "
            f"action={new_action.value} "
            f"input_action={action.value} "
            f"buy={buy_score:.2f} "
            f"sell={sell_score:.2f} "
            f"dominant={dominant_action.value} "
            f"conflict={conflict_ratio:.2f} "
            f"conf={new_confidence:.2f}"
        )
        return new_action, new_confidence, note


def dominate_side(align_score: float, oppose_score: float) -> str:
    if align_score > oppose_score:
        return "align"
    if oppose_score > align_score:
        return "oppose"
    return "flat"


__all__ = [
    "AnalysisView",
    "AnalysisInterpreter",
    "ConflictArbitrationConfig",
    "FusionResult",
    "LLMInfluenceGuard",
    "SignalFusionEngine",
    "dominate_side",
]
