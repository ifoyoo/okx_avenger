"""市场分析器：基于技术指标和结构的确定性分析."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import AppSettings
from core.data.snapshot import MarketSnapshot, build_market_summary

from .logger import build_performance_hint


@dataclass
class TrendAssessment:
    direction: str = "range"
    strength: float = 0.0
    label: str = "震荡整理"
    ema_gap_pct: float = 0.0
    adx: float = 0.0
    higher_timeframe_alignment: float = 0.0


@dataclass
class MomentumAssessment:
    score: float = 0.0
    label: str = "neutral"
    rsi: float = 50.0
    macd_bias: str = "neutral"
    stoch_bias: str = "neutral"
    williams_bias: str = "neutral"


@dataclass
class LevelAssessment:
    supports: List[float] = field(default_factory=list)
    resistances: List[float] = field(default_factory=list)
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    range_position: Optional[float] = None


@dataclass
class RiskAssessment:
    factors: List[str] = field(default_factory=list)
    volatility_ratio: float = 0.0
    regime: str = "normal"
    account_pressure: float = 0.0


@dataclass
class MarketAnalysis:
    """市场分析结果."""

    text: str
    summary: str
    history_hint: str

    trend_strength: float = 0.5
    momentum_score: float = 0.0
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)

    trend: TrendAssessment = field(default_factory=TrendAssessment)
    momentum: MomentumAssessment = field(default_factory=MomentumAssessment)
    levels: LevelAssessment = field(default_factory=LevelAssessment)
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    analysis_version: str = "v2"

    def __post_init__(self) -> None:
        if self.trend.strength == 0.0 and self.trend_strength != 0.0:
            self.trend.strength = float(self.trend_strength)
        else:
            self.trend_strength = float(self.trend.strength)

        if self.momentum.score == 0.0 and self.momentum_score != 0.0:
            self.momentum.score = float(self.momentum_score)
        else:
            self.momentum_score = float(self.momentum.score)

        if not self.levels.supports and self.support_levels:
            self.levels.supports = list(self.support_levels)
        else:
            self.support_levels = list(self.levels.supports)

        if not self.levels.resistances and self.resistance_levels:
            self.levels.resistances = list(self.resistance_levels)
        else:
            self.resistance_levels = list(self.levels.resistances)

        if self.levels.nearest_support is None and self.levels.supports:
            self.levels.nearest_support = max(self.levels.supports)
        if self.levels.nearest_resistance is None and self.levels.resistances:
            self.levels.nearest_resistance = min(self.levels.resistances)

        if not self.risk.factors and self.risk_factors:
            self.risk.factors = list(self.risk_factors)
        else:
            self.risk_factors = list(self.risk.factors)


class MarketAnalyzer:
    """市场分析器."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def analyze(
        self,
        inst_id: str,
        timeframe: str,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]] = None,
        snapshot: Optional[MarketSnapshot] = None,
        account_snapshot: Optional[Dict[str, float]] = None,
        risk_note: Optional[str] = None,
        position_entries: Optional[List[Dict[str, Any]]] = None,
        perf_stats: Optional[Dict[str, Any]] = None,
        daily_stats: Optional[Dict[str, Any]] = None,
    ) -> MarketAnalysis:
        """执行市场分析（纯技术指标 + 结构）."""

        del position_entries, perf_stats, daily_stats

        summary_text = build_market_summary(features.tail(25), higher_features, snapshot)
        history_hint = build_performance_hint(inst_id, timeframe)

        trend = self._assess_trend(features, higher_features)
        momentum = self._assess_momentum(features)
        levels = self._assess_levels(features)
        risk = self._assess_risk(
            features=features,
            higher_features=higher_features,
            risk_note=risk_note,
            account_snapshot=account_snapshot,
            levels=levels,
        )
        analysis_text = self._compose_analysis_text(
            inst_id=inst_id,
            timeframe=timeframe,
            latest=features.iloc[-1],
            trend=trend,
            momentum=momentum,
            levels=levels,
            risk=risk,
            account_snapshot=account_snapshot,
        )

        return MarketAnalysis(
            text=analysis_text,
            summary=summary_text,
            history_hint=history_hint,
            trend_strength=trend.strength,
            momentum_score=momentum.score,
            support_levels=list(levels.supports),
            resistance_levels=list(levels.resistances),
            risk_factors=list(risk.factors),
            trend=trend,
            momentum=momentum,
            levels=levels,
            risk=risk,
        )

    def _calculate_trend_strength(
        self,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
    ) -> float:
        return self._assess_trend(features, higher_features).strength

    def _calculate_momentum(self, features: pd.DataFrame) -> float:
        return self._assess_momentum(features).score

    def _find_support_resistance(
        self, features: pd.DataFrame
    ) -> tuple[List[float], List[float]]:
        levels = self._assess_levels(features)
        return levels.supports, levels.resistances

    def _identify_risks(
        self,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
        risk_note: Optional[str],
        account_snapshot: Optional[Dict[str, float]],
    ) -> List[str]:
        levels = self._assess_levels(features)
        return self._assess_risk(
            features=features,
            higher_features=higher_features,
            risk_note=risk_note,
            account_snapshot=account_snapshot,
            levels=levels,
        ).factors

    def _assess_trend(
        self,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
    ) -> TrendAssessment:
        latest = features.iloc[-1]
        ema_fast = float(latest.get("ema_fast", 0.0) or 0.0)
        ema_slow = float(latest.get("ema_slow", 0.0) or 0.0)
        adx = float(latest.get("adx", 0.0) or 0.0)
        adx_pos = float(latest.get("adx_pos", 0.0) or 0.0)
        adx_neg = float(latest.get("adx_neg", 0.0) or 0.0)

        gap_pct = (ema_fast - ema_slow) / ema_slow if abs(ema_slow) > 1e-9 else 0.0
        gap_sign = 1.0 if gap_pct > 0 else -1.0 if gap_pct < 0 else 0.0
        di_bias = 1.0 if adx_pos > adx_neg else -1.0 if adx_neg > adx_pos else 0.0
        alignment = self._higher_timeframe_alignment(higher_features)

        direction_score = gap_sign + di_bias * 0.6 + alignment * 0.5
        if direction_score > 0.35:
            direction = "bullish"
        elif direction_score < -0.35:
            direction = "bearish"
        else:
            direction = "range"

        strength = min(abs(gap_pct) * 18.0, 0.55)
        strength += min(max(adx - 15.0, 0.0) / 50.0, 0.35)
        strength += min(abs(alignment) * 0.15, 0.1)
        strength = max(0.0, min(1.0, strength))

        label = self._trend_label(direction, strength, adx, alignment)
        return TrendAssessment(
            direction=direction,
            strength=strength,
            label=label,
            ema_gap_pct=gap_pct,
            adx=adx,
            higher_timeframe_alignment=alignment,
        )

    def _assess_momentum(self, features: pd.DataFrame) -> MomentumAssessment:
        latest = features.iloc[-1]
        rsi = float(latest.get("rsi", 50.0) or 50.0)
        macd = float(latest.get("macd", 0.0) or 0.0)
        macd_signal = float(latest.get("macd_signal", 0.0) or 0.0)
        stoch_k = float(latest.get("stoch_k", 50.0) or 50.0)
        stoch_d = float(latest.get("stoch_d", 50.0) or 50.0)
        williams_r = float(latest.get("williams_r", -50.0) or -50.0)

        rsi_component = max(-1.0, min(1.0, (rsi - 50.0) / 25.0)) * 0.35
        macd_component = 0.25 if macd > macd_signal else -0.25 if macd < macd_signal else 0.0
        stoch_component = 0.2 if stoch_k > max(stoch_d, 60.0) else -0.2 if stoch_k < min(stoch_d, 40.0) else 0.0
        williams_component = 0.2 if williams_r > -35.0 else -0.2 if williams_r < -65.0 else 0.0

        score = rsi_component + macd_component + stoch_component + williams_component
        score = max(-1.0, min(1.0, score))

        if rsi >= 75.0 and stoch_k >= 80.0 and williams_r >= -20.0:
            label = "overbought"
        elif rsi <= 25.0 and stoch_k <= 20.0 and williams_r <= -80.0:
            label = "oversold"
        elif score >= 0.2:
            label = "bullish"
        elif score <= -0.2:
            label = "bearish"
        else:
            label = "neutral"

        return MomentumAssessment(
            score=score,
            label=label,
            rsi=rsi,
            macd_bias="bullish" if macd > macd_signal else "bearish" if macd < macd_signal else "neutral",
            stoch_bias="bullish" if stoch_k > stoch_d else "bearish" if stoch_k < stoch_d else "neutral",
            williams_bias="overbought" if williams_r >= -20.0 else "oversold" if williams_r <= -80.0 else "neutral",
        )

    def _assess_levels(self, features: pd.DataFrame) -> LevelAssessment:
        supports, resistances = self._extract_support_resistance(features)
        if features is None or features.empty:
            return LevelAssessment(supports=supports, resistances=resistances)

        recent = features.tail(min(len(features), 50))
        high = float(recent["high"].max() or 0.0)
        low = float(recent["low"].min() or 0.0)
        close = float(recent.iloc[-1].get("close", 0.0) or 0.0)
        range_position = None
        if high > low:
            range_position = max(0.0, min(1.0, (close - low) / (high - low)))
        nearest_support = max(supports) if supports else None
        nearest_resistance = min(resistances) if resistances else None
        return LevelAssessment(
            supports=supports,
            resistances=resistances,
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance,
            range_position=range_position,
        )

    def _extract_support_resistance(
        self, features: pd.DataFrame
    ) -> tuple[List[float], List[float]]:
        if features is None or len(features) < 12:
            return [], []
        lows = features["low"].astype(float).tolist()
        highs = features["high"].astype(float).tolist()
        close = float(features.iloc[-1].get("close", 0.0) or 0.0)
        if close <= 0:
            return [], []

        local_lows: List[float] = []
        local_highs: List[float] = []
        lookback = min(len(features), 200)
        start = max(2, len(features) - lookback)
        end = len(features) - 2
        for idx in range(start, end):
            low_window = lows[idx - 2: idx + 3]
            high_window = highs[idx - 2: idx + 3]
            center_low = lows[idx]
            center_high = highs[idx]
            if low_window and center_low <= min(low_window):
                local_lows.append(center_low)
            if high_window and center_high >= max(high_window):
                local_highs.append(center_high)

        tolerance = max(
            0.0015,
            min(
                0.02,
                float(features["close"].pct_change().abs().tail(40).mean() or 0.003) * 1.8,
            ),
        )
        supports = self._cluster_levels(
            [value for value in local_lows if value < close],
            current_price=close,
            tolerance_ratio=tolerance,
            top_n=3,
            reverse=True,
        )
        resistances = self._cluster_levels(
            [value for value in local_highs if value > close],
            current_price=close,
            tolerance_ratio=tolerance,
            top_n=3,
            reverse=False,
        )
        return supports, resistances

    def _assess_risk(
        self,
        *,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
        risk_note: Optional[str],
        account_snapshot: Optional[Dict[str, float]],
        levels: LevelAssessment,
    ) -> RiskAssessment:
        del higher_features

        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0) or 0.0)
        atr = float(latest.get("atr", 0.0) or 0.0)
        volatility_ratio = (atr / close) if close > 0 else 0.0

        factors: List[str] = []
        if risk_note:
            factors.append(risk_note)

        regime = "normal"
        if volatility_ratio >= 0.05:
            factors.append("高波动率")
            regime = "hot"
        elif 0 < volatility_ratio <= 0.01:
            regime = "calm"

        if levels.nearest_support is not None and close > 0:
            support_distance = abs(close - levels.nearest_support) / close
            if support_distance <= 0.008:
                factors.append("接近支撑位")

        if levels.nearest_resistance is not None and close > 0:
            resistance_distance = abs(levels.nearest_resistance - close) / close
            if resistance_distance <= 0.008:
                factors.append("接近阻力位")

        account_pressure = 0.0
        if account_snapshot:
            available_pct = float(account_snapshot.get("available_pct", 1.0) or 0.0)
            account_pressure = max(0.0, min(1.0, 1.0 - available_pct))
            if available_pct < 0.3:
                factors.append("可用资金不足")

        return RiskAssessment(
            factors=self._dedupe_strings(factors),
            volatility_ratio=volatility_ratio,
            regime=regime,
            account_pressure=account_pressure,
        )

    def _compose_analysis_text(
        self,
        *,
        inst_id: str,
        timeframe: str,
        latest: pd.Series,
        trend: TrendAssessment,
        momentum: MomentumAssessment,
        levels: LevelAssessment,
        risk: RiskAssessment,
        account_snapshot: Optional[Dict[str, float]],
    ) -> str:
        close = float(latest.get("close", 0.0) or 0.0)
        cci = float(latest.get("cci", 0.0) or 0.0)
        macd = float(latest.get("macd", 0.0) or 0.0)
        macd_signal = float(latest.get("macd_signal", 0.0) or 0.0)
        ema_fast = float(latest.get("ema_fast", 0.0) or 0.0)
        ema_slow = float(latest.get("ema_slow", 0.0) or 0.0)
        adx = float(latest.get("adx", 0.0) or 0.0)
        stoch_k = float(latest.get("stoch_k", 50.0) or 50.0)
        stoch_d = float(latest.get("stoch_d", 50.0) or 50.0)

        sections = [
            f"**交易对**：{inst_id} @ {timeframe}",
            f"**当前价格**：{close:.4f}",
            f"**趋势**：{trend.label}（ADX={adx:.1f}，趋势强度={trend.strength:.2f}）",
            f"**EMA**：快线 {ema_fast:.4f} / 慢线 {ema_slow:.4f}（gap {trend.ema_gap_pct:+.2%}）",
            f"**动量**：{momentum.label}（score={momentum.score:+.2f}，RSI={momentum.rsi:.1f}）",
            f"**MACD**：{macd:.4f} / 信号 {macd_signal:.4f}（{momentum.macd_bias}）",
            f"**CCI**：{cci:.1f}",
            f"**KDJ**：K={stoch_k:.1f} / D={stoch_d:.1f}",
        ]

        if levels.supports:
            sections.append("**支撑位**：" + " / ".join(f"{item:.4f}" for item in levels.supports))
        if levels.resistances:
            sections.append("**阻力位**：" + " / ".join(f"{item:.4f}" for item in levels.resistances))
        if levels.range_position is not None:
            sections.append(f"**区间位置**：{levels.range_position:.0%}")

        if account_snapshot:
            equity = float(account_snapshot.get("equity", 0.0) or 0.0)
            available = float(account_snapshot.get("available", 0.0) or 0.0)
            sections.append(f"**账户权益**：{equity:.2f} USDT")
            sections.append(f"**可用资金**：{available:.2f} USDT")

        if risk.factors:
            sections.append("**风险**：" + "; ".join(risk.factors))

        sections.append("**建议**：" + self._build_advice(trend, momentum, risk))
        return "\n".join(sections)

    @staticmethod
    def _cluster_levels(
        levels: List[float],
        *,
        current_price: float,
        tolerance_ratio: float,
        top_n: int,
        reverse: bool,
    ) -> List[float]:
        if not levels:
            return []
        ordered = sorted(levels, reverse=reverse)
        clusters: List[List[float]] = []
        for level in ordered:
            if level <= 0:
                continue
            matched = False
            for cluster in clusters:
                pivot = sum(cluster) / len(cluster)
                if abs(level - pivot) / max(current_price, 1e-12) <= tolerance_ratio:
                    cluster.append(level)
                    matched = True
                    break
            if not matched:
                clusters.append([level])
        merged = [sum(cluster) / len(cluster) for cluster in clusters]
        merged = sorted(merged, reverse=reverse)
        return [round(item, 6) for item in merged[: max(1, top_n)]]

    @staticmethod
    def _higher_timeframe_alignment(
        higher_features: Optional[Dict[str, pd.DataFrame]],
    ) -> float:
        if not higher_features:
            return 0.0
        votes: List[float] = []
        for df in higher_features.values():
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            ema_fast = float(latest.get("ema_fast", 0.0) or 0.0)
            ema_slow = float(latest.get("ema_slow", 0.0) or 0.0)
            slope = 0.0
            if len(df) >= 5:
                slope = float(df["ema_fast"].iloc[-1] - df["ema_fast"].iloc[-5])
            if ema_fast > ema_slow and slope >= 0:
                votes.append(1.0)
            elif ema_fast < ema_slow and slope <= 0:
                votes.append(-1.0)
            else:
                votes.append(0.0)
        if not votes:
            return 0.0
        return sum(votes) / len(votes)

    @staticmethod
    def _trend_label(
        direction: str,
        strength: float,
        adx: float,
        alignment: float,
    ) -> str:
        suffix = ""
        if alignment >= 0.35:
            suffix = "，多周期同向"
        elif alignment <= -0.35:
            suffix = "，高周期偏空"
        elif abs(alignment) >= 0.1:
            suffix = "，高周期分歧"

        if direction == "bullish":
            if strength >= 0.7:
                return f"强势上涨{suffix}"
            if strength >= 0.45:
                return f"偏多上涨{suffix}"
            return f"弱势偏多{suffix}"
        if direction == "bearish":
            if strength >= 0.7:
                return f"强势下跌{suffix}"
            if strength >= 0.45:
                return f"偏空下跌{suffix}"
            return f"弱势偏空{suffix}"
        if adx < 15:
            return "震荡无趋势"
        return "震荡整理"

    @staticmethod
    def _build_advice(
        trend: TrendAssessment,
        momentum: MomentumAssessment,
        risk: RiskAssessment,
    ) -> str:
        if "高波动率" in risk.factors:
            return "波动偏高，优先等待更好的入场位置。"
        if trend.direction == "bullish" and momentum.label == "overbought":
            return "上涨趋势仍在，但短线偏热，谨防回调。"
        if trend.direction == "bearish" and momentum.label == "oversold":
            return "下跌趋势仍在，但短线偏冷，警惕技术性反抽。"
        if trend.direction == "bullish" and momentum.score > 0.15:
            return "趋势与动量同向，优先顺势观察做多机会。"
        if trend.direction == "bearish" and momentum.score < -0.15:
            return "趋势与动量同向，优先顺势观察做空机会。"
        if trend.direction == "range":
            return "震荡行情，等待方向确认后再行动。"
        return "信号未完全共振，保持观察。"

    @staticmethod
    def _dedupe_strings(items: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for item in items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result


__all__ = [
    "MarketAnalyzer",
    "MarketAnalysis",
    "TrendAssessment",
    "MomentumAssessment",
    "LevelAssessment",
    "RiskAssessment",
]
