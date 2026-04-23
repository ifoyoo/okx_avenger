"""客观策略信号生成器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from core.models import SignalAction
from .candle_selection import select_signal_features
from .plugins import SignalPluginManager
from .positioning import VOL_TARGET


RSI_STRONG_OVERSOLD = 25
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
RSI_STRONG_OVERBOUGHT = 75
EMA_GAP_THRESHOLD = 0.001
LIQUIDITY_WINDOW = 20
MIN_LIQUIDITY_RATIO = 0.1
MIN_NOTIONAL_USD = 1000.0
LOW_VOL_ENV_THRESHOLD = 0.004
HIGH_VOL_ENV_THRESHOLD = 0.025
GOLDEN_CROSS_LOOKBACK = 3
PULLBACK_VOLUME_RATIO = 0.75
PULLBACK_FAST_TOL = 0.015
PULLBACK_SLOW_TOL = 0.025
VOLUME_BREAKOUT_RATIO = 2.0
BOX_LOOKBACK = 60
BOX_MIN_WIDTH = 0.05
BOX_MAX_WIDTH = 0.22

# Notes that represent pure mean-reversion "reversal-only" hints from the indicator block.
# In the new gate+template flow, these are treated as confirmation only (not initiators).
REVERSAL_ONLY_INDICATOR_NOTES: frozenset[str] = frozenset(
    {
        "RSI 极度超卖",
        "RSI 极度超买",
        "价格触及布林下轨并伴随动能修复",
        "价格触及布林上轨且动能减弱",
    }
)


@dataclass
class ObjectiveSignal:
    name: str
    action: SignalAction
    confidence: float
    note: str


class ObjectiveSignalGenerator:
    """客观信号拆解."""

    def __init__(self, plugin_manager: Optional[SignalPluginManager] = None) -> None:
        self.plugin_manager = plugin_manager or SignalPluginManager()

    def build(
        self,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Tuple[ObjectiveSignal, ...]:
        signal_features, _source = select_signal_features(features)
        indicator_action, indicator_conf, indicator_note = self._indicator_opinion(signal_features)
        signals: List[ObjectiveSignal] = [
            ObjectiveSignal("indicator", indicator_action, indicator_conf, indicator_note)
        ]
        higher_action, higher_conf, higher_note = self._higher_timeframe_bias(higher_features)
        if higher_note:
            signals.append(ObjectiveSignal("higher_timeframe", higher_action, higher_conf, higher_note))
        signals.extend(self.plugin_manager.generate(self, signal_features, higher_features))
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
        signal_features, _source = select_signal_features(features)
        window = min(len(signal_features), LIQUIDITY_WINDOW)
        if window < 5:
            return True, None
        recent = signal_features.tail(window)
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

    def _trend_regime_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 25:
            return None
        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0) or 0.0)
        fast = float(latest.get("ema_fast", 0.0) or 0.0)
        slow = float(latest.get("ema_slow", 0.0) or 0.0)
        rsi = float(latest.get("rsi", 50.0) or 50.0)
        adx = float(latest.get("adx", 0.0) or 0.0)
        if close <= 0 or fast <= 0 or slow <= 0:
            return None
        gap_pct = (fast - slow) / slow if slow else 0.0
        slope = 0.0
        if len(features) >= 6:
            slope = float(features["ema_fast"].iloc[-1] - features["ema_fast"].iloc[-6])
        note = f"EMA gap {gap_pct:+.2%}, RSI {rsi:.1f}, ADX {adx:.1f}"
        if fast > slow and slope > 0 and 45 <= rsi <= 72:
            conf = 0.55
            if adx >= 22:
                conf = 0.62
            return ObjectiveSignal("bull_trend", SignalAction.BUY, conf, note)
        if fast < slow and slope < 0 and 28 <= rsi <= 55:
            conf = 0.55
            if adx >= 22:
                conf = 0.62
            return ObjectiveSignal("bull_trend", SignalAction.SELL, conf, note)
        return None

    def _ma_golden_cross_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 30:
            return None
        fast = features["ema_fast"]
        slow = features["ema_slow"]
        cross_up = ((fast.shift(1) <= slow.shift(1)) & (fast > slow)).tail(GOLDEN_CROSS_LOOKBACK).any()
        cross_down = ((fast.shift(1) >= slow.shift(1)) & (fast < slow)).tail(GOLDEN_CROSS_LOOKBACK).any()
        vol_ratio = self._volume_ratio(features, window=5)
        note = f"近{GOLDEN_CROSS_LOOKBACK}根交叉检测, 量比 {vol_ratio:.2f}x"
        if cross_up:
            conf = 0.62 if vol_ratio >= 1.2 else 0.56
            return ObjectiveSignal("ma_golden_cross", SignalAction.BUY, conf, note)
        if cross_down:
            conf = 0.62 if vol_ratio >= 1.2 else 0.56
            return ObjectiveSignal("ma_golden_cross", SignalAction.SELL, conf, note)
        return None

    def _shrink_pullback_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 25:
            return None
        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0) or 0.0)
        fast = float(latest.get("ema_fast", 0.0) or 0.0)
        slow = float(latest.get("ema_slow", 0.0) or 0.0)
        if close <= 0 or fast <= 0 or slow <= 0:
            return None
        vol_ratio = self._volume_ratio(features, window=5)
        near_fast = abs(close - fast) / fast <= PULLBACK_FAST_TOL
        near_slow = abs(close - slow) / slow <= PULLBACK_SLOW_TOL
        slope = 0.0
        if len(features) >= 6:
            slope = float(features["ema_slow"].iloc[-1] - features["ema_slow"].iloc[-6])
        if fast > slow and slope >= 0 and vol_ratio <= PULLBACK_VOLUME_RATIO and (near_fast or near_slow):
            anchor = "EMA_FAST" if near_fast else "EMA_SLOW"
            note = f"缩量回踩 {anchor}, 量比 {vol_ratio:.2f}x"
            return ObjectiveSignal("shrink_pullback", SignalAction.BUY, 0.64, note)
        if fast < slow and slope <= 0 and vol_ratio <= PULLBACK_VOLUME_RATIO and (near_fast or near_slow):
            anchor = "EMA_FAST" if near_fast else "EMA_SLOW"
            note = f"缩量反抽 {anchor}, 量比 {vol_ratio:.2f}x"
            return ObjectiveSignal("shrink_pullback", SignalAction.SELL, 0.64, note)
        return None

    def _price_volume_breakout_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 35:
            return None
        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0) or 0.0)
        if close <= 0:
            return None
        prev_high = float(features["high"].iloc[-21:-1].max() or 0.0)
        prev_low = float(features["low"].iloc[-21:-1].min() or 0.0)
        vol_ratio = self._volume_ratio(features, window=20)
        note = f"突破位 H:{prev_high:.6f}/L:{prev_low:.6f}, 量比 {vol_ratio:.2f}x"
        if vol_ratio >= VOLUME_BREAKOUT_RATIO and close > prev_high:
            conf = min(0.82, 0.6 + (vol_ratio - VOLUME_BREAKOUT_RATIO) * 0.08)
            return ObjectiveSignal("volume_breakout", SignalAction.BUY, conf, note + " 向上突破")
        if vol_ratio >= VOLUME_BREAKOUT_RATIO and close < prev_low:
            conf = min(0.82, 0.6 + (vol_ratio - VOLUME_BREAKOUT_RATIO) * 0.08)
            return ObjectiveSignal("volume_breakout", SignalAction.SELL, conf, note + " 向下突破")
        return None

    def _box_oscillation_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < BOX_LOOKBACK:
            return None
        recent = features.tail(BOX_LOOKBACK)
        high = float(recent["high"].max() or 0.0)
        low = float(recent["low"].min() or 0.0)
        close = float(recent["close"].iloc[-1] or 0.0)
        if high <= low or close <= 0 or low <= 0:
            return None
        width = (high - low) / low
        if width < BOX_MIN_WIDTH or width > BOX_MAX_WIDTH:
            return None
        pos = (close - low) / (high - low)
        vol_ratio = self._volume_ratio(features, window=10)
        note = f"箱体宽度 {width:.1%}, 区间位置 {pos:.1%}, 量比 {vol_ratio:.2f}x"
        if pos <= 0.18 and vol_ratio <= 1.3:
            return ObjectiveSignal("box_oscillation", SignalAction.BUY, 0.58, note + " 贴近箱底")
        if pos >= 0.82 and vol_ratio <= 1.3:
            return ObjectiveSignal("box_oscillation", SignalAction.SELL, 0.58, note + " 接近箱顶")
        return None

    def _one_yang_three_yin_signal(self, features: pd.DataFrame) -> Optional[ObjectiveSignal]:
        if len(features) < 6:
            return None
        bars = features.tail(5).reset_index(drop=True)
        opens = bars["open"].astype(float)
        closes = bars["close"].astype(float)
        lows = bars["low"].astype(float)
        vols = bars["volume"].astype(float)
        first_open, first_close = float(opens.iloc[0]), float(closes.iloc[0])
        if first_open <= 0 or first_close <= 0:
            return None
        body1 = first_close - first_open
        body1_pct = body1 / first_open if first_open else 0.0
        if body1 <= 0 or body1_pct < 0.008:
            return None
        mid_bodies = closes.iloc[1:4] - opens.iloc[1:4]
        mid_ok = (mid_bodies <= 0).sum() >= 2 and (lows.iloc[1:4] >= first_open * 0.99).all()
        if not mid_ok:
            return None
        vol_shrink = vols.iloc[1:4].mean() < vols.iloc[0] * 0.9
        last_open, last_close = float(opens.iloc[4]), float(closes.iloc[4])
        if last_close <= last_open or last_close <= first_close:
            return None
        conf = 0.66 if vol_shrink else 0.6
        note = (
            f"一阳夹三阴成立, 首阳涨幅 {body1_pct:.1%}, "
            f"末阳突破 {((last_close / first_close) - 1):+.1%}"
        )
        return ObjectiveSignal("one_yang_three_yin", SignalAction.BUY, conf, note)

    @staticmethod
    def _volume_ratio(features: pd.DataFrame, window: int) -> float:
        if len(features) <= 1:
            return 1.0
        window = max(2, min(window, len(features) - 1))
        recent = features["volume"].tail(window + 1)
        latest = float(recent.iloc[-1] or 0.0)
        base = float(recent.iloc[:-1].mean() or 0.0)
        if base <= 0 or latest <= 0:
            return 1.0
        return latest / base

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


__all__ = ["ObjectiveSignal", "ObjectiveSignalGenerator", "REVERSAL_ONLY_INDICATOR_NOTES"]
