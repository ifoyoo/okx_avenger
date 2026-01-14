"""策略逻辑与信号解析."""

from __future__ import annotations

import json
import re
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
from .positioning import PositionSizer, VOL_TARGET, GLOBAL_POSITION_CAP


ACTION_KEYWORDS = {
    SignalAction.BUY: ["buy", "long", "做多", "买入", "多单", "看涨", "偏多", "多头"],
    SignalAction.SELL: ["sell", "short", "做空", "卖出", "空单", "看跌", "偏空", "空头"],
}
RSI_STRONG_OVERSOLD = 25
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
RSI_STRONG_OVERBOUGHT = 75
EMA_GAP_THRESHOLD = 0.001
LIQUIDITY_WINDOW = 20
MIN_LIQUIDITY_RATIO = 0.2
MIN_NOTIONAL_USD = 2000.0
LOW_VOL_ENV_THRESHOLD = 0.004
HIGH_VOL_ENV_THRESHOLD = 0.025


@dataclass
class AnalysisView:
    """分析视图（原 LLM 视图）."""
    action: SignalAction
    confidence: float
    reason: str = ""
    risk: str = ""
    time_horizon: str = ""
    invalid_conditions: str = ""
    raw_text: str = ""


@dataclass
class ObjectiveSignal:
    name: str
    action: SignalAction
    confidence: float
    note: str


@dataclass
class FusionResult:
    action: SignalAction
    confidence: float
    notes: Tuple[str, ...]


@dataclass
class StrategyOutput:
    trade_signal: TradeSignal
    objective_signals: Tuple[ObjectiveSignal, ...]
    analysis_view: AnalysisView
    fusion_notes: Tuple[str, ...]


class AnalysisInterpreter:
    """负责解析与校验分析结构（原 LLM 解释器）."""

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


class ObjectiveSignalGenerator:
    """客观信号拆解."""

    def build(
        self,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Tuple[ObjectiveSignal, ...]:
        indicator_action, indicator_conf, indicator_note = self._indicator_opinion(features)
        signals: List[ObjectiveSignal] = [
            ObjectiveSignal("indicator", indicator_action, indicator_conf, indicator_note)
        ]
        higher_action, higher_conf, higher_note = self._higher_timeframe_bias(higher_features)
        if higher_note:
            signals.append(ObjectiveSignal("higher_timeframe", higher_action, higher_conf, higher_note))
        volume_signal = self._volume_pressure_signal(features)
        if volume_signal:
            signals.append(volume_signal)
        vola_signal = self._volatility_breakout_signal(features)
        if vola_signal:
            signals.append(vola_signal)
        return tuple(signals)

    def volatility_regime(
        self,
        higher_features: Optional[Dict[str, pd.DataFrame]],
    ) -> Tuple[float, Optional[str]]:
        if not higher_features:
            return 1.0, None
        ratios = []
        for df in higher_features.values():
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            close = float(latest.get("close", 0.0) or 0.0)
            atr = float(latest.get("atr", 0.0) or 0.0)
            if close > 0 and atr > 0:
                ratios.append(atr / close)
        if not ratios:
            return 1.0, None
        avg_ratio = sum(ratios) / len(ratios)
        if avg_ratio < LOW_VOL_ENV_THRESHOLD:
            return 0.6, f"波动过滤：高阶 ATR/Close {avg_ratio:.4f} 偏低，仓位折半。"
        if avg_ratio > HIGH_VOL_ENV_THRESHOLD:
            return 0.85, f"波动警报：高阶 ATR/Close {avg_ratio:.4f} 过高，降低杠杆。"
        return 1.0, None

    def liquidity_snapshot(self, features: pd.DataFrame) -> Tuple[bool, Optional[str]]:
        window = min(len(features), LIQUIDITY_WINDOW)
        if window < 5:
            return True, None
        recent = features.tail(window)
        latest = recent.iloc[-1]
        volume = float(latest.get("volume", 0.0) or 0.0)
        avg_volume = float(recent["volume"].mean() or 0.0)
        latest_notional = float(latest.get("volume_usd", 0.0) or 0.0)
        avg_notional = float(recent["volume_usd"].mean() or 0.0)
        if avg_volume <= 0:
            return True, None
        ratio = volume / avg_volume if avg_volume else 0.0
        breaches = []
        if ratio < MIN_LIQUIDITY_RATIO:
            breaches.append(f"当前成交量仅为均值的 {ratio:.0%}")
        if 0 < avg_notional < MIN_NOTIONAL_USD:
            breaches.append(f"{window} 根均值成交额 {avg_notional:.0f} USD < {MIN_NOTIONAL_USD:.0f}")
        if latest_notional and latest_notional < MIN_NOTIONAL_USD * 0.5:
            breaches.append(f"最近一根成交额仅 {latest_notional:.0f} USD")
        if not breaches:
            return True, None
        return False, "流动性过滤：" + "，".join(breaches)

    def trade_plan(self, latest: pd.Series, action: SignalAction) -> Optional[str]:
        if action == SignalAction.HOLD:
            return None
        close = float(latest.get("close", 0.0) or 0.0)
        atr = float(latest.get("atr", 0.0) or 0.0)
        if close <= 0 or atr <= 0:
            return None
        stop_mult = 1.2
        tp1_mult = 1.5
        tp2_mult = 2.5
        if action == SignalAction.BUY:
            stop = max(0.0, close - atr * stop_mult)
            tp1 = close + atr * tp1_mult
            tp2 = close + atr * tp2_mult
        else:
            stop = close + atr * stop_mult
            tp1 = max(0.0, close - atr * tp1_mult)
            tp2 = max(0.0, close - atr * tp2_mult)
        return f"执行建议：止损 {stop:.6f}，分批止盈 {tp1:.6f}/{tp2:.6f} (ATR 基准)。"

    @staticmethod
    def _indicator_opinion(features: pd.DataFrame) -> Tuple[SignalAction, float, str]:
        latest = features.iloc[-1]
        rsi = float(latest["rsi"])
        fast = float(latest["ema_fast"])
        slow = float(latest["ema_slow"])
        ema_gap = (fast - slow) / slow if slow else 0.0
        atr = float(latest.get("atr", 0.0))
        close = float(latest.get("close", 0.0))
        atr_pct = (atr / close) if close else 0.0
        macd_value = float(latest.get("macd", 0.0))
        macd_signal = float(latest.get("macd_signal", 0.0))
        macd_hist = float(latest.get("macd_hist", 0.0))
        bb_high = float(latest.get("bb_high", 0.0))
        bb_low = float(latest.get("bb_low", 0.0))
        bb_width = float(latest.get("bb_width", 0.0))
        bb_range = bb_high - bb_low
        bb_pos = 0.5
        if bb_range > 0:
            bb_pos = min(1.0, max(0.0, (close - bb_low) / bb_range))
        recent = features.tail(5)
        fast_slope = float(recent["ema_fast"].iloc[-1] - recent["ema_fast"].iloc[0])
        slow_slope = float(recent["ema_slow"].iloc[-1] - recent["ema_slow"].iloc[0])
        adaptive = ObjectiveSignalGenerator._adaptive_thresholds(features)
        strong_oversold = adaptive["strong_oversold"]
        oversold = adaptive["oversold"]
        overbought = adaptive["overbought"]
        strong_overbought = adaptive["strong_overbought"]
        gap_threshold = adaptive["gap"]
        reason: List[str] = []
        if rsi <= strong_oversold:
            reason.append("RSI 极度超卖")
            return SignalAction.BUY, 0.8, "；".join(reason)
        if rsi <= oversold and fast >= slow:
            reason.append("RSI 超卖且快线上穿慢线")
            return SignalAction.BUY, 0.7, "；".join(reason)
        if fast_slope > 0 and slow_slope > 0 and fast >= slow and 35 < rsi < 60:
            reason.append("EMA 多头排列且斜率向上")
            return SignalAction.BUY, 0.6, "；".join(reason)
        if macd_hist > 0 and macd_value >= macd_signal and fast >= slow:
            reason.append("MACD 多头动能增强")
            return SignalAction.BUY, 0.6, "；".join(reason)
        if ema_gap > gap_threshold and rsi < 55:
            reason.append("EMA 正向偏离")
            return SignalAction.BUY, 0.55, "；".join(reason)
        if bb_width > 0 and bb_pos < 0.15 and macd_hist >= -0.0005:
            reason.append("价格触及布林下轨并伴随动能修复")
            return SignalAction.BUY, 0.55, "；".join(reason)
        if rsi >= strong_overbought:
            reason.append("RSI 极度超买")
            return SignalAction.SELL, 0.8, "；".join(reason)
        if rsi >= overbought and fast <= slow:
            reason.append("RSI 超买且快线下穿慢线")
            return SignalAction.SELL, 0.7, "；".join(reason)
        if fast_slope < 0 and slow_slope < 0 and fast <= slow and 40 < rsi < 65:
            reason.append("EMA 空头排列且斜率向下")
            return SignalAction.SELL, 0.6, "；".join(reason)
        if macd_hist < 0 and macd_value <= macd_signal and fast <= slow:
            reason.append("MACD 空头动能增强")
            return SignalAction.SELL, 0.6, "；".join(reason)
        if ema_gap < -gap_threshold and rsi > 45:
            reason.append("EMA 负向偏离")
            return SignalAction.SELL, 0.55, "；".join(reason)
        if bb_width > 0 and bb_pos > 0.85 and macd_hist <= 0.0005:
            reason.append("价格触及布林上轨且动能减弱")
            return SignalAction.SELL, 0.55, "；".join(reason)
        note = adaptive.get("note", "指标无明显优势")
        if atr_pct > adaptive.get("atr_warning", 0.05):
            note = "高波动，指标置信度降低"
        return SignalAction.HOLD, 0.4, note

    def _volume_pressure_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 20:
            return None
        window = min(len(features), 40)
        recent = features.tail(window)
        avg_vol = float(recent["volume"].iloc[:-1].mean() or 0.0)
        latest_vol = float(recent["volume"].iloc[-1] or 0.0)
        if avg_vol <= 0 or latest_vol <= 0:
            return None
        ratio = latest_vol / avg_vol
        obv_series = recent.get("obv")
        mfi_series = recent.get("mfi")
        if obv_series is None or mfi_series is None:
            return None
        start_idx = max(len(recent) - 6, 0)
        obv_delta = float(obv_series.iloc[-1] - obv_series.iloc[start_idx])
        price_delta = float(recent["close"].iloc[-1] - recent["close"].iloc[start_idx])
        mfi = float(mfi_series.iloc[-1])
        note = f"成交量 {ratio:.1f}x, OBV Δ{obv_delta:.0f}, MFI {mfi:.1f}"
        if ratio >= 1.8 and obv_delta > 0 and price_delta > 0 and mfi >= 45:
            conf = min(0.85, 0.55 + (ratio - 1.8) * 0.15)
            return ObjectiveSignal("volume_pressure", SignalAction.BUY, conf, note)
        if ratio >= 1.8 and obv_delta < 0 and price_delta < 0 and mfi <= 55:
            conf = min(0.85, 0.55 + (ratio - 1.8) * 0.15)
            return ObjectiveSignal("volume_pressure", SignalAction.SELL, conf, note)
        if ratio < 0.8 and abs(price_delta) < 0.002:
            return ObjectiveSignal("volume_pressure", SignalAction.HOLD, 0.3, note)
        return None

    def _volatility_breakout_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 50:
            return None
        widths = features["bb_width"].tail(60)
        if widths.empty:
            return None
        current_width = float(widths.iloc[-1] or 0.0)
        prev_mean = float(widths.iloc[:-1].mean() or 0.0)
        if prev_mean <= 0:
            return None
        squeeze = current_width < prev_mean * 0.7
        expansion = current_width > prev_mean * 1.2 and widths.iloc[-3] < prev_mean * 0.8
        high_roll = features["high"].rolling(20).max()
        low_roll = features["low"].rolling(20).min()
        if len(high_roll) < 21 or len(low_roll) < 21:
            return None
        prev_high = float(high_roll.iloc[-2])
        prev_low = float(low_roll.iloc[-2])
        close = float(features["close"].iloc[-1])
        note = f"宽度 {current_width:.4f} (均值 {prev_mean:.4f})"
        if expansion and close > prev_high:
            return ObjectiveSignal("volatility_breakout", SignalAction.BUY, 0.6, note + " 向上突破")
        if expansion and close < prev_low:
            return ObjectiveSignal("volatility_breakout", SignalAction.SELL, 0.6, note + " 向下突破")
        if squeeze:
            return ObjectiveSignal("volatility_breakout", SignalAction.HOLD, 0.35, note + " 压缩等待")
        return None

    @staticmethod
    def _higher_timeframe_bias(
        features_map: Optional[Dict[str, pd.DataFrame]]
    ) -> Tuple[SignalAction, float, str]:
        if not features_map:
            return SignalAction.HOLD, 0.0, ""
        score = 0.0
        notes = []
        for tf, df in features_map.items():
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            rsi = float(latest.get("rsi", 50.0))
            fast = float(latest.get("ema_fast", latest.get("close", 0.0)))
            slow = float(latest.get("ema_slow", fast))
            slope = 0.0
            if len(df) >= 5:
                slope = float(df["ema_fast"].iloc[-1] - df["ema_fast"].iloc[-5])
            bias = 0.0
            direction = "震荡"
            if fast >= slow and rsi >= 55:
                bias = 1.0
                direction = "偏多"
            elif fast <= slow and rsi <= 45:
                bias = -1.0
                direction = "偏空"
            elif slope > 0 and rsi >= 50:
                bias = 0.5
                direction = "回暖"
            elif slope < 0 and rsi <= 50:
                bias = -0.5
                direction = "走弱"
            if bias != 0.0:
                notes.append(f"{tf}: {direction} (RSI {rsi:.1f})")
            score += bias
        if not notes:
            return SignalAction.HOLD, 0.0, ""
        avg_strength = min(1.0, abs(score) / len(notes))
        note_text = "；".join(notes)
        if score > 0.5:
            return SignalAction.BUY, avg_strength, note_text
        if score < -0.5:
            return SignalAction.SELL, avg_strength, note_text
        return SignalAction.HOLD, avg_strength, f"方向分歧：{note_text}"

    @staticmethod
    def _adaptive_thresholds(features: pd.DataFrame) -> Dict[str, float]:
        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0))
        atr = float(latest.get("atr", 0.0))
        atr_pct = (atr / close) if close else 0.0
        try:
            rolling_vol = float(features["returns"].rolling(50).std().iloc[-1])
        except Exception:
            rolling_vol = 0.0
        vol_metric = max(atr_pct, rolling_vol)
        if vol_metric <= 0:
            vol_factor = 1.0
        else:
            vol_factor = min(1.5, max(0.7, VOL_TARGET / vol_metric))
        inv_factor = min(1.3, max(0.7, 2 - vol_factor))
        strong_oversold = max(15.0, RSI_STRONG_OVERSOLD * vol_factor)
        oversold = max(20.0, RSI_OVERSOLD * vol_factor)
        strong_overbought = min(90.0, RSI_STRONG_OVERBOUGHT * inv_factor)
        overbought = min(strong_overbought - 5.0, RSI_OVERBOUGHT * inv_factor)
        if overbought <= oversold + 2:
            overbought = oversold + 5
        if strong_overbought <= overbought + 2:
            strong_overbought = overbought + 5
        gap = EMA_GAP_THRESHOLD * inv_factor
        note = f"波动调整因子 {vol_factor:.2f}"
        return {
            "strong_oversold": strong_oversold,
            "oversold": oversold,
            "overbought": overbought,
            "strong_overbought": strong_overbought,
            "gap": gap,
            "atr_warning": max(0.05, atr_pct * 1.1),
            "note": note,
        }


class SignalFusionEngine:
    """融合客观指标与分析观点（原 LLM 观点）."""

    SUPPORTIVE_NAMES = {"volume_pressure", "volatility_breakout"}

    def fuse(self, objective_signals: Sequence[ObjectiveSignal], analysis_view: AnalysisView) -> FusionResult:
        indicator = self._get_signal(objective_signals, "indicator")
        higher_tf = self._get_signal(objective_signals, "higher_timeframe")
        base_action = indicator.action if indicator else SignalAction.HOLD
        base_conf = indicator.confidence if indicator else 0.4
        notes: List[str] = []
        if higher_tf and higher_tf.action != SignalAction.HOLD:
            if higher_tf.action == base_action:
                base_conf = min(1.0, base_conf + 0.15 * max(0.5, higher_tf.confidence))
            else:
                base_conf = max(0.2, base_conf - 0.2 * max(0.5, higher_tf.confidence))
            notes.append(f"多周期：{higher_tf.note}")
        for support in objective_signals:
            if support.name not in self.SUPPORTIVE_NAMES or support.action == SignalAction.HOLD:
                continue
            label = "成交量" if support.name == "volume_pressure" else "波动" if support.name == "volatility_breakout" else support.name
            if base_action == SignalAction.HOLD:
                base_action = support.action
                base_conf = support.confidence
            elif support.action == base_action:
                base_conf = min(1.0, base_conf + 0.1 * max(0.3, support.confidence))
            else:
                base_conf = max(0.2, base_conf - 0.1 * max(0.3, support.confidence))
            notes.append(f"{label}：{support.note}")
        action, confidence = self._combine_actions(base_action, base_conf, analysis_view.action, analysis_view.confidence)
        return FusionResult(action=action, confidence=confidence, notes=tuple(note for note in notes if note))

    def fuse_indicator_only(self, objective_signals: Sequence[ObjectiveSignal]) -> FusionResult:
        """纯指标模式的信号融合，不使用 LLM."""
        indicator = self._get_signal(objective_signals, "indicator")
        higher_tf = self._get_signal(objective_signals, "higher_timeframe")
        base_action = indicator.action if indicator else SignalAction.HOLD
        base_conf = indicator.confidence if indicator else 0.4
        notes: List[str] = []
        if higher_tf and higher_tf.action != SignalAction.HOLD:
            if higher_tf.action == base_action:
                base_conf = min(1.0, base_conf + 0.15 * max(0.5, higher_tf.confidence))
            else:
                base_conf = max(0.2, base_conf - 0.2 * max(0.5, higher_tf.confidence))
            notes.append(f"多周期：{higher_tf.note}")
        for support in objective_signals:
            if support.name not in self.SUPPORTIVE_NAMES or support.action == SignalAction.HOLD:
                continue
            label = "成交量" if support.name == "volume_pressure" else "波动" if support.name == "volatility_breakout" else support.name
            if base_action == SignalAction.HOLD:
                base_action = support.action
                base_conf = support.confidence
            elif support.action == base_action:
                base_conf = min(1.0, base_conf + 0.1 * max(0.3, support.confidence))
            else:
                base_conf = max(0.2, base_conf - 0.1 * max(0.3, support.confidence))
            notes.append(f"{label}：{support.note}")
        notes.append("纯指标模式：未使用 LLM 分析")
        return FusionResult(action=base_action, confidence=base_conf, notes=tuple(notes))

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
    ) -> Tuple[SignalAction, float]:
        if indicator_action == llm_action:
            return indicator_action, min(1.0, max(indicator_conf, llm_conf))
        if llm_action == SignalAction.HOLD:
            return indicator_action, max(0.2, indicator_conf * 0.9)
        if indicator_action == SignalAction.HOLD:
            return llm_action, max(0.2, llm_conf * 0.9)
        if indicator_conf > llm_conf + 0.15:
            return indicator_action, max(0.2, indicator_conf - 0.1)
        if llm_conf > indicator_conf + 0.15:
            return llm_action, max(0.2, llm_conf - 0.1)
        return SignalAction.HOLD, min(indicator_conf, llm_conf) * 0.5


class Strategy:
    """结合客观指标、市场分析及风险过滤生成交易信号."""

    def __init__(self) -> None:
        self.signal_generator = ObjectiveSignalGenerator()
        self.analysis_interpreter = AnalysisInterpreter()
        self.fusion_engine = SignalFusionEngine()
        self.position_sizer = PositionSizer()

    def generate_signal(
        self,
        context: StrategyContext,
        features: pd.DataFrame,
        analysis_text: str,
        higher_features: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> StrategyOutput:
        objective_signals = self.signal_generator.build(features, higher_features)

        # 根据配置决定是否使用分析
        if context.enable_analysis:
            analysis_view = self.analysis_interpreter.parse(analysis_text)
            fusion = self.fusion_engine.fuse(objective_signals, analysis_view)
        else:
            # 纯指标模式：使用默认分析视图（HOLD）
            analysis_view = AnalysisView(
                action=SignalAction.HOLD,
                confidence=0.0,
                reason="分析已禁用，仅使用技术指标",
                raw_text="纯指标模式"
            )
            fusion = self.fusion_engine.fuse_indicator_only(objective_signals)

        latest = features.iloc[-1]
        liquidity_ok, liquidity_note = self.signal_generator.liquidity_snapshot(features)
        env_factor, env_note = self.signal_generator.volatility_regime(higher_features)
        notes = list(fusion.notes)
        if env_note:
            notes.append(env_note)
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
            llm_view=analysis_view,
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
            llm_view=analysis_view,
            fusion_notes=tuple(notes),
        )

    @staticmethod
    def _build_reason_sections(
        objective_signals: Sequence[ObjectiveSignal],
        llm_view: AnalysisView,
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
            }
            label = label_map.get(sig.name, sig.name)
            sections.append(f"{label}：{sig.action.value.upper()} (置信 {sig.confidence:.2f}) - {sig.note}")
        reason_text = llm_view.reason or analysis_text.strip()
        sections.append(
            f"分析观点：{llm_view.action.value.upper()} (置信 {llm_view.confidence:.2f}) - {reason_text}"
        )
        if llm_view.risk:
            sections.append(f"风险提示：{llm_view.risk}")
        if llm_view.time_horizon:
            sections.append(f"适用周期：{llm_view.time_horizon}")
        if llm_view.invalid_conditions:
            sections.append(f"失效条件：{llm_view.invalid_conditions}")
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
        # kind == "tp" => 顺着方向，"sl" => 反方向
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
            # 百分比触发统一走市价，确保触发后立即平仓
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

    @staticmethod
    def _indicator_opinion(features: pd.DataFrame) -> Tuple[SignalAction, float, str]:
        latest = features.iloc[-1]
        rsi = float(latest["rsi"])
        fast = float(latest["ema_fast"])
        slow = float(latest["ema_slow"])
        ema_gap = (fast - slow) / slow if slow else 0.0
        atr = float(latest.get("atr", 0.0))
        close = float(latest.get("close", 0.0))
        atr_pct = (atr / close) if close else 0.0
        macd_value = float(latest.get("macd", 0.0))
        macd_signal = float(latest.get("macd_signal", 0.0))
        macd_hist = float(latest.get("macd_hist", 0.0))
        bb_high = float(latest.get("bb_high", 0.0))
        bb_low = float(latest.get("bb_low", 0.0))
        bb_width = float(latest.get("bb_width", 0.0))
        bb_range = bb_high - bb_low
        bb_pos = 0.5
        if bb_range > 0:
            bb_pos = min(1.0, max(0.0, (close - bb_low) / bb_range))
        recent = features.tail(5)
        fast_slope = float(recent["ema_fast"].iloc[-1] - recent["ema_fast"].iloc[0])
        slow_slope = float(recent["ema_slow"].iloc[-1] - recent["ema_slow"].iloc[0])
        adaptive = Strategy._adaptive_thresholds(features)
        strong_oversold = adaptive["strong_oversold"]
        oversold = adaptive["oversold"]
        overbought = adaptive["overbought"]
        strong_overbought = adaptive["strong_overbought"]
        gap_threshold = adaptive["gap"]
        reason = []
        if rsi <= strong_oversold:
            reason.append("RSI 极度超卖")
            return SignalAction.BUY, 0.8, "；".join(reason)
        if rsi <= oversold and fast >= slow:
            reason.append("RSI 超卖且快线上穿慢线")
            return SignalAction.BUY, 0.7, "；".join(reason)
        if fast_slope > 0 and slow_slope > 0 and fast >= slow and 35 < rsi < 60:
            reason.append("EMA 多头排列且斜率向上")
            return SignalAction.BUY, 0.6, "；".join(reason)
        if macd_hist > 0 and macd_value >= macd_signal and fast >= slow:
            reason.append("MACD 多头动能增强")
            return SignalAction.BUY, 0.6, "；".join(reason)
        if ema_gap > gap_threshold and rsi < 55:
            reason.append("EMA 正向偏离")
            return SignalAction.BUY, 0.55, "；".join(reason)
        if bb_width > 0 and bb_pos < 0.15 and macd_hist >= -0.0005:
            reason.append("价格触及布林下轨并伴随动能修复")
            return SignalAction.BUY, 0.55, "；".join(reason)
        if rsi >= strong_overbought:
            reason.append("RSI 极度超买")
            return SignalAction.SELL, 0.8, "；".join(reason)
        if rsi >= overbought and fast <= slow:
            reason.append("RSI 超买且快线下穿慢线")
            return SignalAction.SELL, 0.7, "；".join(reason)
        if fast_slope < 0 and slow_slope < 0 and fast <= slow and 40 < rsi < 65:
            reason.append("EMA 空头排列且斜率向下")
            return SignalAction.SELL, 0.6, "；".join(reason)
        if macd_hist < 0 and macd_value <= macd_signal and fast <= slow:
            reason.append("MACD 空头动能增强")
            return SignalAction.SELL, 0.6, "；".join(reason)
        if ema_gap < -gap_threshold and rsi > 45:
            reason.append("EMA 负向偏离")
            return SignalAction.SELL, 0.55, "；".join(reason)
        if bb_width > 0 and bb_pos > 0.85 and macd_hist <= 0.0005:
            reason.append("价格触及布林上轨且动能减弱")
            return SignalAction.SELL, 0.55, "；".join(reason)
        note = adaptive.get("note", "指标无明显优势")
        if atr_pct > adaptive.get("atr_warning", 0.05):
            note = "高波动，指标置信度降低"
        return SignalAction.HOLD, 0.4, note

    @staticmethod
    def _adaptive_thresholds(features: pd.DataFrame) -> Dict[str, float]:
        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0))
        atr = float(latest.get("atr", 0.0))
        atr_pct = (atr / close) if close else 0.0
        try:
            rolling_vol = float(features["returns"].rolling(50).std().iloc[-1])
        except Exception:
            rolling_vol = 0.0
        vol_metric = max(atr_pct, rolling_vol)
        if vol_metric <= 0:
            vol_factor = 1.0
        else:
            vol_factor = min(1.5, max(0.7, VOL_TARGET / vol_metric))
        inv_factor = min(1.3, max(0.7, 2 - vol_factor))
        strong_oversold = max(15.0, RSI_STRONG_OVERSOLD * vol_factor)
        oversold = max(20.0, RSI_OVERSOLD * vol_factor)
        strong_overbought = min(90.0, RSI_STRONG_OVERBOUGHT * inv_factor)
        overbought = min(strong_overbought - 5.0, RSI_OVERBOUGHT * inv_factor)
        if overbought <= oversold + 2:
            overbought = oversold + 5
        if strong_overbought <= overbought + 2:
            strong_overbought = overbought + 5
        gap = EMA_GAP_THRESHOLD * inv_factor
        note = f"波动调整因子 {vol_factor:.2f}"
        return {
            "strong_oversold": strong_oversold,
            "oversold": oversold,
            "overbought": overbought,
            "strong_overbought": strong_overbought,
            "gap": gap,
            "atr_warning": max(0.05, atr_pct * 1.1),
            "note": note,
        }

    def _parse_llm_analysis(self, text: str) -> LLMView:
        structured = self._extract_structured_json(text)
        if structured:
            action_text = structured.get("action", "").strip()
            action = self._normalize_action(action_text)
            confidence = self._sanitize_confidence(structured.get("confidence"))
            reason = structured.get("reason", "").strip()
            risk = structured.get("risk", "").strip()
            time_horizon = structured.get("time_horizon") or structured.get("horizon") or ""
            invalid = (
                structured.get("invalid_conditions")
                or structured.get("invalid_condition")
                or structured.get("invalid")
                or ""
            )
            return LLMView(
                action=action,
                confidence=confidence,
                reason=reason,
                risk=risk,
                time_horizon=str(time_horizon).strip(),
                invalid_conditions=str(invalid).strip(),
            )
        lowered = text.lower()
        for action, keywords in ACTION_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                conf = self._extract_confidence(text)
                return LLMView(action=action, confidence=conf, reason=text.strip())
        conf = self._extract_confidence(text)
        return LLMView(action=SignalAction.HOLD, confidence=conf, reason=text.strip())

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
    def _higher_timeframe_bias(
        features_map: Optional[Dict[str, pd.DataFrame]]
    ) -> Tuple[SignalAction, float, str]:
        if not features_map:
            return SignalAction.HOLD, 0.0, ""
        score = 0.0
        notes = []
        for tf, df in features_map.items():
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            rsi = float(latest.get("rsi", 50.0))
            fast = float(latest.get("ema_fast", latest.get("close", 0.0)))
            slow = float(latest.get("ema_slow", fast))
            slope = 0.0
            if len(df) >= 5:
                slope = float(df["ema_fast"].iloc[-1] - df["ema_fast"].iloc[-5])
            bias = 0.0
            direction = "震荡"
            if fast >= slow and rsi >= 55:
                bias = 1.0
                direction = "偏多"
            elif fast <= slow and rsi <= 45:
                bias = -1.0
                direction = "偏空"
            elif slope > 0 and rsi >= 50:
                bias = 0.5
                direction = "回暖"
            elif slope < 0 and rsi <= 50:
                bias = -0.5
                direction = "走弱"
            if bias != 0.0:
                notes.append(f"{tf}: {direction} (RSI {rsi:.1f})")
            score += bias
        if not notes:
            return SignalAction.HOLD, 0.0, ""
        avg_strength = min(1.0, abs(score) / len(notes))
        note_text = "；".join(notes)
        if score > 0.5:
            return SignalAction.BUY, avg_strength, note_text
        if score < -0.5:
            return SignalAction.SELL, avg_strength, note_text
        return SignalAction.HOLD, avg_strength, f"方向分歧：{note_text}"

    @staticmethod
    def _combine_actions(
        indicator_action: SignalAction,
        indicator_conf: float,
        llm_action: SignalAction,
        llm_conf: float,
    ) -> Tuple[SignalAction, float]:
        if indicator_action == llm_action:
            return indicator_action, min(1.0, max(indicator_conf, llm_conf))
        if llm_action == SignalAction.HOLD:
            return indicator_action, max(0.2, indicator_conf * 0.9)
        if indicator_action == SignalAction.HOLD:
            return llm_action, max(0.2, llm_conf * 0.9)
        if indicator_conf > llm_conf + 0.15:
            return indicator_action, max(0.2, indicator_conf - 0.1)
        if llm_conf > indicator_conf + 0.15:
            return llm_action, max(0.2, llm_conf - 0.1)
        return SignalAction.HOLD, min(indicator_conf, llm_conf) * 0.5

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

    @staticmethod
    def _dynamic_position_size(
        context: StrategyContext,
        latest: pd.Series,
        confidence: float,
        action: SignalAction,
        trend_bias: SignalAction = SignalAction.HOLD,
        env_factor: float = 1.0,
    ) -> float:
        base = max(context.max_position or 0.001, 0.0001)
        close = float(latest.get("close", 0.0))
        atr = float(latest.get("atr", 0.0))
        atr_pct = atr / close if close else 0.0
        if close > 0 and context.account_equity:
            max_by_equity = (context.account_equity * 0.02) / close
            if max_by_equity > 0:
                base = min(base, max_by_equity)
        if close > 0 and context.available_balance:
            max_by_balance = (context.available_balance * 0.05) / close
            if max_by_balance > 0:
                base = min(base, max_by_balance)
        if atr_pct <= 0:
            vol_factor = 1.0
        else:
            vol_factor = min(1.5, max(0.4, VOL_TARGET / atr_pct))
        dynamic = base * confidence * vol_factor * max(0.3, env_factor)
        if trend_bias != SignalAction.HOLD:
            if trend_bias == action:
                dynamic *= 1.1
            else:
                dynamic *= 0.75
        floor = base * 0.2
        size = min(GLOBAL_POSITION_CAP, max(dynamic, floor))
        return max(size, 0.0)

    def _liquidity_filter(self, features: pd.DataFrame) -> Tuple[bool, str]:
        window = min(len(features), LIQUIDITY_WINDOW)
        if window < 5:
            return True, ""
        recent = features.tail(window)
        latest = recent.iloc[-1]
        volume = float(latest.get("volume", 0.0) or 0.0)
        try:
            avg_volume = float(recent["volume"].mean())
        except Exception:
            avg_volume = 0.0
        latest_notional = float(latest.get("volume_usd", 0.0) or 0.0)
        try:
            avg_notional = float(recent["volume_usd"].mean())
        except Exception:
            avg_notional = 0.0
        if avg_volume <= 0:
            return True, ""
        ratio = volume / avg_volume if avg_volume else 0.0
        breaches = []
        if ratio < MIN_LIQUIDITY_RATIO:
            breaches.append(f"当前成交量仅为均值的 {ratio:.0%}")
        if 0 < avg_notional < MIN_NOTIONAL_USD:
            breaches.append(f"{window} 根均值成交额 {avg_notional:.0f} USD < {MIN_NOTIONAL_USD:.0f}")
        if latest_notional and latest_notional < MIN_NOTIONAL_USD * 0.5:
            breaches.append(f"最近一根成交额仅 {latest_notional:.0f} USD")
        if not breaches:
            return True, ""
        return False, "流动性过滤：" + "，".join(breaches)

    def _volatility_regime(
        self,
        higher_features: Optional[Dict[str, pd.DataFrame]],
    ) -> Tuple[float, str]:
        if not higher_features:
            return 1.0, ""
        ratios = []
        for df in higher_features.values():
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            close = float(latest.get("close", 0.0) or 0.0)
            atr = float(latest.get("atr", 0.0) or 0.0)
            if close > 0 and atr > 0:
                ratios.append(atr / close)
        if not ratios:
            return 1.0, ""
        avg_ratio = sum(ratios) / len(ratios)
        if avg_ratio < LOW_VOL_ENV_THRESHOLD:
            return 0.6, f"波动过滤：高阶 ATR/Close {avg_ratio:.4f} 偏低，仓位折半。"
        if avg_ratio > HIGH_VOL_ENV_THRESHOLD:
            return 0.85, f"波动警报：高阶 ATR/Close {avg_ratio:.4f} 过高，降低杠杆。"
        return 1.0, ""

    @staticmethod
    def _trade_plan(latest: pd.Series, action: SignalAction) -> Optional[str]:
        if action == SignalAction.HOLD:
            return None
        close = float(latest.get("close", 0.0) or 0.0)
        atr = float(latest.get("atr", 0.0) or 0.0)
        if close <= 0 or atr <= 0:
            return None
        stop_mult = 1.2
        tp1_mult = 1.5
        tp2_mult = 2.5
        if action == SignalAction.BUY:
            stop = max(0.0, close - atr * stop_mult)
            tp1 = close + atr * tp1_mult
            tp2 = close + atr * tp2_mult
        else:
            stop = close + atr * stop_mult
            tp1 = max(0.0, close - atr * tp1_mult)
            tp2 = max(0.0, close - atr * tp2_mult)
        return f"执行建议：止损 {stop:.6f}，分批止盈 {tp1:.6f}/{tp2:.6f} (ATR 基准)。"
