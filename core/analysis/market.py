"""市场分析器：基于技术指标和结构的确定性分析（替代 LLM）."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import AppSettings
from core.data.snapshot import MarketSnapshot, build_market_summary

from .logger import build_performance_hint


@dataclass
class MarketAnalysis:
    """市场分析结果（替代 LLMAnalysis）."""

    text: str  # 结构化分析文本
    summary: str  # 市场摘要
    history_hint: str  # 历史表现提示

    # 新增：结构化数据（阶段 2-3 实现）
    trend_strength: float = 0.5  # 趋势强度 0-1
    momentum_score: float = 0.0  # 动量评分 -1 到 1
    support_levels: List[float] = None  # 支撑位
    resistance_levels: List[float] = None  # 阻力位
    risk_factors: List[str] = None  # 风险因素

    def __post_init__(self):
        if self.support_levels is None:
            self.support_levels = []
        if self.resistance_levels is None:
            self.resistance_levels = []
        if self.risk_factors is None:
            self.risk_factors = []


class MarketAnalyzer:
    """市场分析器（替代 LLMService）."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        # 不再需要 AI 配置

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

        # 1. 生成市场摘要（复用现有逻辑）
        summary_text = build_market_summary(
            features.tail(25), higher_features, snapshot
        )

        # 2. 历史表现提示
        history_hint = build_performance_hint(inst_id, timeframe)

        # 3. 趋势强度分析（阶段 2-3 实现）
        trend_strength = self._calculate_trend_strength(features, higher_features)

        # 4. 动量评分（阶段 2 实现）
        momentum_score = self._calculate_momentum(features)

        # 5. 支撑/阻力位（阶段 3 实现）
        support_levels, resistance_levels = self._find_support_resistance(features)

        # 6. 风险因素识别
        risk_factors = self._identify_risks(
            features, higher_features, risk_note, account_snapshot
        )

        # 7. 生成结构化分析文本
        analysis_text = self._compose_analysis_text(
            inst_id,
            timeframe,
            features,
            higher_features,
            trend_strength,
            momentum_score,
            support_levels,
            resistance_levels,
            risk_factors,
            account_snapshot,
            perf_stats,
            daily_stats,
        )

        return MarketAnalysis(
            text=analysis_text,
            summary=summary_text,
            history_hint=history_hint,
            trend_strength=trend_strength,
            momentum_score=momentum_score,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            risk_factors=risk_factors,
        )

    def _calculate_trend_strength(
        self, features: pd.DataFrame, higher_features: Optional[Dict]
    ) -> float:
        """计算趋势强度（阶段 2-3 实现）."""
        # TODO: 基于 ADX + EMA slope + MACD
        latest = features.iloc[-1]

        # 简单实现：基于 EMA 快慢线距离
        ema_fast = latest.get("ema_fast", 0)
        ema_slow = latest.get("ema_slow", 0)

        if ema_slow > 0:
            diff_pct = abs(ema_fast - ema_slow) / ema_slow
            # 归一化到 0-1
            strength = min(diff_pct * 10, 1.0)
        else:
            strength = 0.5

        return strength

    def _calculate_momentum(self, features: pd.DataFrame) -> float:
        """计算动量评分（阶段 2 实现）."""
        # TODO: 基于 RSI + Stochastic + 成交量
        latest = features.iloc[-1]

        # 简单实现：基于 RSI
        rsi = latest.get("rsi", 50)

        # 归一化到 -1 到 1
        if rsi > 70:
            momentum = (rsi - 70) / 30  # 超买
        elif rsi < 30:
            momentum = (rsi - 30) / 30  # 超卖
        else:
            momentum = (rsi - 50) / 20  # 中性

        return max(-1.0, min(1.0, momentum))

    def _find_support_resistance(
        self, features: pd.DataFrame
    ) -> tuple[List[float], List[float]]:
        """识别支撑/阻力位（阶段 3 实现）."""
        # TODO: 基于 pivot 高低点
        return [], []

    def _identify_risks(
        self,
        features: pd.DataFrame,
        higher_features: Optional[Dict],
        risk_note: Optional[str],
        account_snapshot: Optional[Dict[str, float]],
    ) -> List[str]:
        """识别风险因素."""
        risks = []

        if risk_note:
            risks.append(risk_note)

        # 检查波动率
        latest = features.iloc[-1]
        atr = latest.get("atr", 0)
        close = latest.get("close", 0)

        if close > 0 and atr / close > 0.05:
            risks.append("高波动率")

        # 检查账户风险
        if account_snapshot:
            available_pct = account_snapshot.get("available_pct", 1.0)
            if available_pct < 0.3:
                risks.append("可用资金不足")

        return risks

    def _compose_analysis_text(
        self,
        inst_id: str,
        timeframe: str,
        features: pd.DataFrame,
        higher_features: Optional[Dict],
        trend_strength: float,
        momentum_score: float,
        support: List[float],
        resistance: List[float],
        risks: List[str],
        account_snapshot: Optional[Dict[str, float]],
        perf_stats: Optional[Dict[str, Any]],
        daily_stats: Optional[Dict[str, Any]],
    ) -> str:
        """生成结构化分析文本."""
        latest = features.iloc[-1]
        sections = []

        # 基本信息
        close = latest.get("close", 0)
        sections.append(f"**交易对**：{inst_id} @ {timeframe}")
        sections.append(f"**当前价格**：{close:.4f}")

        # 趋势分析（增强）
        adx = latest.get("adx", 0)
        adx_pos = latest.get("adx_pos", 0)
        adx_neg = latest.get("adx_neg", 0)

        if adx > 25:
            if adx_pos > adx_neg:
                trend_desc = f"强势上涨（ADX={adx:.1f}, +DI={adx_pos:.1f} > -DI={adx_neg:.1f}）"
            else:
                trend_desc = f"强势下跌（ADX={adx:.1f}, -DI={adx_neg:.1f} > +DI={adx_pos:.1f}）"
        elif adx > 15:
            trend_desc = f"中等趋势（ADX={adx:.1f}）"
        else:
            trend_desc = f"震荡无趋势（ADX={adx:.1f}）"
        sections.append(f"**趋势**：{trend_desc}")

        # 动量分析（增强）
        rsi = latest.get("rsi", 50)
        stoch_k = latest.get("stoch_k", 50)
        stoch_d = latest.get("stoch_d", 50)
        kdj_j = latest.get("kdj_j", 50)
        williams_r = latest.get("williams_r", -50)

        momentum_signals = []
        if rsi > 70:
            momentum_signals.append("RSI超买")
        elif rsi < 30:
            momentum_signals.append("RSI超卖")

        if stoch_k > 80:
            momentum_signals.append("KDJ超买")
        elif stoch_k < 20:
            momentum_signals.append("KDJ超卖")

        if williams_r > -20:
            momentum_signals.append("W%R超买")
        elif williams_r < -80:
            momentum_signals.append("W%R超卖")

        momentum_desc = "、".join(momentum_signals) if momentum_signals else "中性"
        sections.append(f"**动量**：{momentum_desc}")
        sections.append(f"  - RSI: {rsi:.1f}, Stoch K/D: {stoch_k:.1f}/{stoch_d:.1f}, KDJ J: {kdj_j:.1f}")
        sections.append(f"  - Williams %R: {williams_r:.1f}")

        # CCI 分析
        cci = latest.get("cci", 0)
        if cci > 100:
            cci_desc = "超买区域"
        elif cci < -100:
            cci_desc = "超卖区域"
        else:
            cci_desc = "正常区间"
        sections.append(f"**CCI**：{cci:.1f}（{cci_desc}）")

        # MACD 分析
        macd = latest.get("macd", 0)
        macd_signal = latest.get("macd_signal", 0)
        macd_hist = latest.get("macd_hist", 0)

        if macd > macd_signal:
            macd_desc = "金叉（看涨）"
        else:
            macd_desc = "死叉（看跌）"
        sections.append(f"**MACD**：{macd:.4f} / 信号 {macd_signal:.4f}（{macd_desc}）")

        # EMA 分析
        ema_fast = latest.get("ema_fast", 0)
        ema_slow = latest.get("ema_slow", 0)
        if ema_fast > ema_slow:
            ema_desc = "快线在慢线上方（看涨）"
        else:
            ema_desc = "快线在慢线下方（看跌）"
        sections.append(f"**EMA**：{ema_desc}")

        # Ichimoku 分析
        ichimoku_conv = latest.get("ichimoku_conv", 0)
        ichimoku_base = latest.get("ichimoku_base", 0)
        ichimoku_a = latest.get("ichimoku_a", 0)
        ichimoku_b = latest.get("ichimoku_b", 0)

        if close > 0 and ichimoku_a > 0 and ichimoku_b > 0:
            cloud_top = max(ichimoku_a, ichimoku_b)
            cloud_bottom = min(ichimoku_a, ichimoku_b)

            if close > cloud_top:
                ichimoku_desc = "价格在云上方（强势看涨）"
            elif close < cloud_bottom:
                ichimoku_desc = "价格在云下方（强势看跌）"
            else:
                ichimoku_desc = "价格在云中（震荡）"

            if ichimoku_conv > ichimoku_base:
                ichimoku_desc += "，转换线>基准线"
            else:
                ichimoku_desc += "，转换线<基准线"

            sections.append(f"**Ichimoku**：{ichimoku_desc}")

        # 布林带
        bb_high = latest.get("bb_high", 0)
        bb_low = latest.get("bb_low", 0)
        if close > 0 and bb_high > 0 and bb_low > 0:
            if close > bb_high:
                bb_desc = "价格突破上轨（超买）"
            elif close < bb_low:
                bb_desc = "价格突破下轨（超卖）"
            else:
                bb_position = (close - bb_low) / (bb_high - bb_low) if (bb_high - bb_low) > 0 else 0.5
                bb_desc = f"价格在布林带内（位置 {bb_position:.0%}）"
            sections.append(f"**布林带**：{bb_desc}")

        # 成交量
        volume = latest.get("volume", 0)
        mfi = latest.get("mfi", 50)
        sections.append(f"**成交量**：{volume:.2f}，MFI: {mfi:.1f}")

        # 账户信息
        if account_snapshot:
            equity = account_snapshot.get("equity", 0)
            available = account_snapshot.get("available", 0)
            sections.append(f"**账户权益**：{equity:.2f} USDT")
            sections.append(f"**可用资金**：{available:.2f} USDT")

        # 风险因素
        if risks:
            sections.append(f"**风险**：{'; '.join(risks)}")

        # 综合建议
        if momentum_score < -0.5 and trend_strength > 0.5:
            sections.append("**建议**：超卖区域且趋势明确，可能存在反弹机会")
        elif momentum_score > 0.5 and trend_strength > 0.5:
            sections.append("**建议**：超买区域且趋势明确，注意回调风险")
        elif adx < 15:
            sections.append("**建议**：震荡行情，等待明确趋势信号")
        else:
            sections.append("**建议**：观察市场，等待更明确的信号")

        return "\n".join(sections)


__all__ = ["MarketAnalyzer", "MarketAnalysis"]
