"""Data ingestion + feature compression utilities."""

from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import time

import pandas as pd

from core.client import MarketDataStream, OKXClient

SNAPSHOT_EXECUTOR_WORKERS = 12


@dataclass
class OrderBookStats:
    spread_pct: float
    imbalance: float
    top_bid: float
    top_ask: float


@dataclass
class TradeStats:
    buy_ratio: float
    avg_size: float
    count: int


@dataclass
class DerivativeStats:
    funding_rate: Optional[float]
    funding_time: Optional[str]
    open_interest: Optional[float]


@dataclass
class TickerStats:
    last: float
    open_24h: Optional[float]
    high_24h: Optional[float]
    low_24h: Optional[float]
    vol_24h: Optional[float]
    vol_ccy_24h: Optional[float]
    sod_utc0: Optional[float]
    sod_utc8: Optional[float]
    change_pct: Optional[float]
    range_pct: Optional[float]


@dataclass
class MarketSnapshot:
    order_book: Optional[OrderBookStats]
    trades: Optional[TradeStats]
    derivatives: Optional[DerivativeStats]
    ticker: Optional[TickerStats]


class MarketSnapshotCollector:
    def __init__(self, client: OKXClient, stream: Optional[MarketDataStream] = None) -> None:
        self.client = client
        self.stream = stream
        self._executor = ThreadPoolExecutor(max_workers=SNAPSHOT_EXECUTOR_WORKERS, thread_name_prefix="snapshot")
        atexit.register(self._executor.shutdown, wait=False)
        self._ticker_cache: Dict[str, Tuple[float, TickerStats]] = {}
        self._deriv_cache: Dict[str, Tuple[float, DerivativeStats]] = {}
        self._cache_ttl = 120.0

    def build(self, inst_id: str) -> MarketSnapshot:
        tasks = {
            "order_book": lambda: self._collect_order_book(inst_id),
            "trades": lambda: self._collect_trades(inst_id),
            "derivatives": lambda: self._collect_derivatives(inst_id),
            "ticker": lambda: self._collect_ticker(inst_id),
        }
        results: Dict[str, Optional[object]] = {key: None for key in tasks}
        if self.stream:
            for key, func in tasks.items():
                try:
                    results[key] = func()
                except Exception:
                    results[key] = None
        else:
            future_map = {self._executor.submit(func): key for key, func in tasks.items()}
            for future in as_completed(future_map):
                key = future_map[future]
                try:
                    results[key] = future.result()
                except Exception:
                    results[key] = None
        return MarketSnapshot(
            order_book=results["order_book"],
            trades=results["trades"],
            derivatives=results["derivatives"],
            ticker=results["ticker"],
        )

    def _collect_order_book(self, inst_id: str) -> Optional[OrderBookStats]:
        if self.stream:
            stats = self.stream.get_order_book_stats(inst_id)
            if stats:
                return OrderBookStats(
                    spread_pct=stats["spread_pct"],
                    imbalance=stats["imbalance"],
                    top_bid=stats["top_bid"],
                    top_ask=stats["top_ask"],
                )
        try:
            resp = self.client.get_order_book(inst_id, depth=5)
            data = resp.get("data") or []
            if not data:
                return None
            entry = data[0]
            bids = entry.get("bids") or []
            asks = entry.get("asks") or []
            if not bids or not asks:
                return None
            top_bid = float(bids[0][0])
            top_ask = float(asks[0][0])
            spread = (top_ask - top_bid) / top_bid if top_bid else 0.0
            bid_volume = sum(float(item[1]) for item in bids[:5])
            ask_volume = sum(float(item[1]) for item in asks[:5])
            total = bid_volume + ask_volume
            imbalance = (bid_volume - ask_volume) / total if total > 0 else 0.0
            return OrderBookStats(spread_pct=spread, imbalance=imbalance, top_bid=top_bid, top_ask=top_ask)
        except Exception:
            return None

    def _collect_trades(self, inst_id: str) -> Optional[TradeStats]:
        if self.stream:
            data = self.stream.get_trade_stats(inst_id)
            if data:
                buy = 0.0
                sell = 0.0
                total_size = 0.0
                count = 0
                for trade in data:
                    try:
                        size = float(trade.get("sz", 0) or 0)
                    except Exception:
                        continue
                    side = str(trade.get("side") or "").lower()
                    total_size += size
                    count += 1
                    if side == "buy":
                        buy += size
                    elif side == "sell":
                        sell += size
                total = buy + sell
                buy_ratio = buy / total if total > 0 else 0.5
                avg_size = total_size / count if count > 0 else 0.0
                return TradeStats(buy_ratio=buy_ratio, avg_size=avg_size, count=count)
        try:
            resp = self.client.get_trades(inst_id, limit=50)
            data = resp.get("data") or []
            if not data:
                return None
            buy = 0.0
            sell = 0.0
            total_size = 0.0
            count = 0
            for trade in data:
                size = float(trade.get("sz", 0) or 0)
                side = str(trade.get("side") or "").lower()
                total_size += size
                count += 1
                if side == "buy":
                    buy += size
                elif side == "sell":
                    sell += size
            total = buy + sell
            buy_ratio = buy / total if total > 0 else 0.5
            avg_size = total_size / count if count > 0 else 0.0
            return TradeStats(buy_ratio=buy_ratio, avg_size=avg_size, count=count)
        except Exception:
            return None

    def _collect_derivatives(self, inst_id: str) -> Optional[DerivativeStats]:
        cached = self._deriv_cache.get(inst_id)
        now = time.time()
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]
        funding_rate = None
        funding_time = None
        open_interest = None
        try:
            resp = self.client.get_funding_rate(inst_id)
            data = resp.get("data") or []
            if data:
                entry = data[0]
                funding_rate = float(entry.get("fundingRate", 0) or 0)
                funding_time = entry.get("fundingTime")
        except Exception:
            pass
        try:
            resp = self.client.get_open_interest(inst_id)
            data = resp.get("data") or []
            if data:
                entry = data[0]
                open_interest = float(entry.get("oi", 0) or 0)
        except Exception:
            pass
        if funding_rate is None and open_interest is None:
            return None
        stats = DerivativeStats(funding_rate=funding_rate, funding_time=funding_time, open_interest=open_interest)
        self._deriv_cache[inst_id] = (now, stats)
        return stats

    def _collect_ticker(self, inst_id: str) -> Optional[TickerStats]:
        now = time.time()
        cached = self._ticker_cache.get(inst_id)
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]
        try:
            resp = self.client.get_ticker(inst_id)
        except Exception:
            return None
        data = resp.get("data") or []
        if not data:
            return None
        entry = data[0]
        try:
            last = float(entry.get("last", 0) or 0.0)
        except Exception:
            last = 0.0
        def _to_float(key: str) -> Optional[float]:
            value = entry.get(key)
            if value in ("", None):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        open_24h = _to_float("open24h")
        high_24h = _to_float("high24h")
        low_24h = _to_float("low24h")
        vol_24h = _to_float("vol24h")
        vol_ccy_24h = _to_float("volCcy24h")
        sod_utc0 = _to_float("sodUtc0")
        sod_utc8 = _to_float("sodUtc8")
        change_pct = None
        if open_24h and open_24h > 0:
            change_pct = (last - open_24h) / open_24h if last else None
        range_pct = None
        if high_24h and low_24h and low_24h > 0:
            range_pct = (high_24h - low_24h) / low_24h
        stats = TickerStats(
            last=last,
            open_24h=open_24h,
            high_24h=high_24h,
            low_24h=low_24h,
            vol_24h=vol_24h,
            vol_ccy_24h=vol_ccy_24h,
            sod_utc0=sod_utc0,
            sod_utc8=sod_utc8,
            change_pct=change_pct,
            range_pct=range_pct,
        )
        self._ticker_cache[inst_id] = (now, stats)
        return stats


def _format_pct(value: float) -> str:
    return f"{value:+.2%}"


def _format_float(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def _recent_returns(df: pd.DataFrame, windows: Tuple[int, ...]) -> List[str]:
    results: List[str] = []
    close = df["close"]
    last_idx = len(close) - 1
    latest = close.iloc[-1]
    for window in windows:
        if last_idx < window or latest <= 0:
            continue
        past = close.iloc[-window]
        if past <= 0:
            continue
        ret = latest / past - 1
        results.append(f"{window}根 { _format_pct(ret) }")
    return results


def _volume_snapshot(df: pd.DataFrame, window: int = 20) -> Optional[str]:
    if len(df) < 2:
        return None
    recent = df.tail(window)
    latest_vol = recent["volume"].iloc[-1]
    avg_vol = recent["volume"].mean()
    if avg_vol <= 0:
        return None
    ratio = latest_vol / avg_vol
    return f"成交量当前为均值的 {ratio:.1f}x"


def _range_position(df: pd.DataFrame, window: int = 50) -> Optional[str]:
    if len(df) < 2:
        return None
    recent = df.tail(window)
    high = recent["high"].max()
    low = recent["low"].min()
    latest = recent["close"].iloc[-1]
    if high <= low:
        return None
    pos = (latest - low) / (high - low)
    return f"{window}根区间位置 {pos*100:.1f}% (高点 {high:.4f} / 低点 {low:.4f})"


def _trend_description(latest: pd.Series) -> str:
    ema_fast = float(latest.get("ema_fast", 0.0) or 0.0)
    ema_slow = float(latest.get("ema_slow", 0.0) or 0.0)
    gap = ema_fast - ema_slow
    gap_pct = gap / ema_slow if abs(ema_slow) > 1e-9 else 0.0
    if gap_pct > 0.002:
        status = "多头偏离"
    elif gap_pct < -0.002:
        status = "空头偏离"
    else:
        status = "均线粘合"
    return f"均线 {status} (gap {gap_pct:+.2%})"


def _rsi_summary(rsi: float) -> str:
    if rsi >= 75:
        return f"RSI {rsi:.1f} 极度超买"
    if rsi >= 65:
        return f"RSI {rsi:.1f} 超买"
    if rsi <= 25:
        return f"RSI {rsi:.1f} 极度超卖"
    if rsi <= 35:
        return f"RSI {rsi:.1f} 超卖"
    return f"RSI {rsi:.1f} 中性"


def _atr_summary(latest: pd.Series) -> Optional[str]:
    close = float(latest.get("close", 0.0) or 0.0)
    atr = float(latest.get("atr", 0.0) or 0.0)
    if close <= 0 or atr <= 0:
        return None
    atr_pct = atr / close
    if atr_pct >= 0.03:
        return f"ATR 占比 {atr_pct:.2%} (高波动)"
    if atr_pct <= 0.01:
        return f"ATR 占比 {atr_pct:.2%} (低波动)"
    return f"ATR 占比 {atr_pct:.2%}"


def describe_base_features(features: pd.DataFrame) -> str:
    latest = features.iloc[-1]
    price = float(latest.get("close", 0.0) or 0.0)
    rsi = float(latest.get("rsi", 0.0) or 0.0)
    lines = [
        f"最新价 {_format_float(price)} USD",
        " / ".join(_recent_returns(features, (5, 15, 30)) or ["最近涨跌不可用"]),
        _rsi_summary(rsi),
        _trend_description(latest),
    ]
    vol_text = _volume_snapshot(features)
    if vol_text:
        lines.append(vol_text)
    rng_text = _range_position(features)
    if rng_text:
        lines.append(rng_text)
    atr_text = _atr_summary(latest)
    if atr_text:
        lines.append(atr_text)
    return "\n".join(lines)


def describe_higher_timeframes(higher_features: Optional[Dict[str, pd.DataFrame]]) -> str:
    if not higher_features:
        return "无额外多周期数据。"
    lines: List[str] = []
    for tf, df in higher_features.items():
        if df is None or df.empty:
            continue
        last = df.iloc[-1]
        close = float(last.get("close", 0.0) or 0.0)
        rsi = float(last.get("rsi", 0.0) or 0.0)
        ema_fast = float(last.get("ema_fast", 0.0) or 0.0)
        ema_slow = float(last.get("ema_slow", 0.0) or 0.0)
        slope = 0.0
        if len(df) >= 5:
            slope = float(df["ema_fast"].iloc[-1] - df["ema_fast"].iloc[-5])
        if ema_fast >= ema_slow and slope > 0:
            trend = "上行偏多"
        elif ema_fast <= ema_slow and slope < 0:
            trend = "下行偏空"
        else:
            trend = "震荡"
        lines.append(f"{tf}: close={_format_float(close)} RSI={rsi:.1f} 趋势{trend}")
    return "\n".join(lines) if lines else "多周期数据为空。"


def _describe_snapshot(snapshot: Optional[MarketSnapshot]) -> Optional[str]:
    if not snapshot:
        return None
    parts: List[str] = []
    if snapshot.ticker:
        tk = snapshot.ticker
        ticker_segments: List[str] = []
        ticker_segments.append(f"最新价 {_format_float(tk.last)} USD")
        if tk.change_pct is not None:
            ticker_segments.append(f"24h 涨幅 {tk.change_pct:+.2%}")
        if tk.range_pct is not None:
            ticker_segments.append(f"区间振幅 {tk.range_pct:.2%}")
        hi = tk.high_24h
        lo = tk.low_24h
        if hi is not None and lo is not None:
            ticker_segments.append(f"高/低 {hi:.4f}/{lo:.4f}")
        vol_quote = tk.vol_ccy_24h or 0.0
        vol_base = tk.vol_24h or 0.0
        if vol_quote or vol_base:
            if vol_quote:
                ticker_segments.append(f"24h 量 {vol_quote:,.0f} USDT")
            elif tk.last and vol_base:
                ticker_segments.append(f"24h 量 ≈{vol_base * tk.last:,.0f} USD")
        sod_ref = tk.sod_utc8 or tk.sod_utc0
        if sod_ref:
            delta = tk.last - sod_ref
            ticker_segments.append(f"日内相对开盘 {delta:+.4f}")
        parts.append("行情：" + "，".join(ticker_segments))
    if snapshot.order_book:
        ob = snapshot.order_book
        parts.append(
            f"盘口：买一 {ob.top_bid:.4f} / 卖一 {ob.top_ask:.4f}，价差 {ob.spread_pct:.3%}，买卖失衡 {ob.imbalance:+.2f}"
        )
    if snapshot.trades:
        tr = snapshot.trades
        parts.append(f"成交：近 {tr.count} 笔，平均量 {tr.avg_size:.4f}，买单占比 {tr.buy_ratio:.0%}")
    if snapshot.derivatives:
        dv = snapshot.derivatives
        if dv.funding_rate is not None:
            parts.append(f"资金费率 {dv.funding_rate:+.4%}")
        if dv.open_interest is not None:
            parts.append(f"持仓量 {dv.open_interest:.0f}")
    return "；".join(parts) if parts else None


def build_market_summary(
    features: pd.DataFrame,
    higher_features: Optional[Dict[str, pd.DataFrame]] = None,
    snapshot: Optional[MarketSnapshot] = None,
) -> str:
    base_summary = describe_base_features(features)
    higher_summary = describe_higher_timeframes(higher_features)
    snapshot_text = _describe_snapshot(snapshot)
    sections = [f"【基础周期】\n{base_summary}", f"【多周期】\n{higher_summary}"]
    if snapshot_text:
        sections.append(f"【盘口/衍生品】\n{snapshot_text}")
    return "\n\n".join(sections)


__all__ = [
    "MarketSnapshot",
    "MarketSnapshotCollector",
    "build_market_summary",
]
