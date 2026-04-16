"""轻量回测器测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from core.backtest.simple import run_backtest_from_features
from core.models import ProtectionRule, SignalAction, TradeProtection, TradeSignal
from core.strategy.core import Strategy


class _DummyStrategy:
    def __init__(self, actions):
        self.actions = list(actions)
        self.idx = 0

    def generate_signal(self, context, features, analysis_text, higher_features):
        action = self.actions[min(self.idx, len(self.actions) - 1)]
        self.idx += 1
        signal = TradeSignal(
            action=action,
            confidence=0.7,
            reason=f"dummy-{action.value}",
            size=1.0 if action != SignalAction.HOLD else 0.0,
        )
        return SimpleNamespace(trade_signal=signal)


def _features(n: int = 16) -> pd.DataFrame:
    rows = []
    for i in range(n):
        close = 100 + i * 0.5
        rows.append(
            {
                "ts": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=5 * i),
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.4,
                "close": close,
            }
        )
    return pd.DataFrame(rows)


class _ProtectionStrategy:
    def __init__(self, actions, protection: TradeProtection) -> None:
        self.actions = list(actions)
        self.idx = 0
        self.protection = protection

    def generate_signal(self, context, features, analysis_text, higher_features):
        action = self.actions[min(self.idx, len(self.actions) - 1)]
        self.idx += 1
        return SimpleNamespace(
            trade_signal=TradeSignal(
                action=action,
                confidence=0.7,
                reason=f"protected-{action.value}",
                size=1.0 if action != SignalAction.HOLD else 0.0,
                protection=self.protection,
            )
        )


def _protection_features(entry_bar: dict) -> pd.DataFrame:
    rows = [
        {
            "ts": pd.Timestamp("2026-01-01T00:00:00Z"),
            "open": 99.8,
            "high": 100.2,
            "low": 99.6,
            "close": 100.0,
            "atr": 1.0,
        },
        {
            "ts": pd.Timestamp("2026-01-01T00:05:00Z"),
            "open": 99.9,
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "atr": 1.0,
        },
        {
            "ts": pd.Timestamp("2026-01-01T00:10:00Z"),
            "open": 100.0,
            "high": 100.4,
            "low": 99.8,
            "close": 100.2,
            "atr": 1.0,
        },
        entry_bar,
        {
            "ts": pd.Timestamp("2026-01-01T00:20:00Z"),
            "open": 100.0,
            "high": 100.1,
            "low": 99.9,
            "close": 100.0,
            "atr": 1.0,
        },
    ]
    return pd.DataFrame(rows)


def _lifecycle_features(entry_bar: dict, trailing_bar: dict) -> pd.DataFrame:
    rows = [
        {
            "ts": pd.Timestamp("2026-01-01T00:00:00Z"),
            "open": 99.8,
            "high": 100.2,
            "low": 99.6,
            "close": 100.0,
            "atr": 2.0,
        },
        {
            "ts": pd.Timestamp("2026-01-01T00:05:00Z"),
            "open": 99.9,
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "atr": 2.0,
        },
        {
            "ts": pd.Timestamp("2026-01-01T00:10:00Z"),
            "open": 100.0,
            "high": 100.4,
            "low": 99.8,
            "close": 100.2,
            "atr": 2.0,
        },
        entry_bar,
        trailing_bar,
    ]
    return pd.DataFrame(rows)


def test_run_backtest_from_features_basic() -> None:
    strategy = _DummyStrategy(
        [
            SignalAction.BUY,
            SignalAction.HOLD,
            SignalAction.HOLD,
            SignalAction.SELL,
            SignalAction.HOLD,
            SignalAction.HOLD,
            SignalAction.BUY,
            SignalAction.HOLD,
            SignalAction.HOLD,
        ]
    )
    result = run_backtest_from_features(
        strategy=strategy,
        features=_features(),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=4,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        max_hold_bars=5,
    )

    assert result.summary.total_trades >= 1
    assert result.summary.bars == 16
    assert result.summary.initial_equity == 1000.0
    assert result.summary.final_equity != 0.0
    assert isinstance(result.to_dict(), dict)


def test_backtest_cost_model_reduces_final_equity() -> None:
    actions = [
        SignalAction.BUY,
        SignalAction.HOLD,
        SignalAction.HOLD,
        SignalAction.SELL,
        SignalAction.HOLD,
        SignalAction.BUY,
        SignalAction.HOLD,
        SignalAction.SELL,
        SignalAction.HOLD,
    ]
    result_low_cost = run_backtest_from_features(
        strategy=_DummyStrategy(actions),
        features=_features(),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=4,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        slippage_ratio=0.0,
        spread_ratio=0.0,
        max_hold_bars=5,
    )
    result_high_cost = run_backtest_from_features(
        strategy=_DummyStrategy(actions),
        features=_features(),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=4,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        slippage_ratio=0.002,
        spread_ratio=0.001,
        max_hold_bars=5,
    )

    assert result_high_cost.summary.final_equity < result_low_cost.summary.final_equity


def test_backtest_exits_on_take_profit_from_trade_protection() -> None:
    strategy = _ProtectionStrategy(
        [SignalAction.BUY, SignalAction.HOLD],
        TradeProtection(
            take_profit=ProtectionRule(mode="ratio", value=0.02),
            stop_loss=ProtectionRule(mode="ratio", value=0.01),
        ),
    )

    result = run_backtest_from_features(
        strategy=strategy,
        features=_protection_features(
            {
                "ts": pd.Timestamp("2026-01-01T00:15:00Z"),
                "open": 100.0,
                "high": 102.5,
                "low": 99.6,
                "close": 101.8,
                "atr": 1.0,
            }
        ),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=2,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        slippage_ratio=0.0,
        spread_ratio=0.0,
        max_hold_bars=5,
    )

    assert result.summary.total_trades == 1
    assert result.trades[0].reason_exit == "take_profit"
    assert result.trades[0].exit_price == 102.0


def test_backtest_exits_on_stop_loss_from_trade_protection() -> None:
    strategy = _ProtectionStrategy(
        [SignalAction.BUY, SignalAction.HOLD],
        TradeProtection(
            take_profit=ProtectionRule(mode="ratio", value=0.02),
            stop_loss=ProtectionRule(mode="ratio", value=0.01),
        ),
    )

    result = run_backtest_from_features(
        strategy=strategy,
        features=_protection_features(
            {
                "ts": pd.Timestamp("2026-01-01T00:15:00Z"),
                "open": 100.0,
                "high": 101.0,
                "low": 98.8,
                "close": 99.1,
                "atr": 1.0,
            }
        ),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=2,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        slippage_ratio=0.0,
        spread_ratio=0.0,
        max_hold_bars=5,
    )

    assert result.summary.total_trades == 1
    assert result.trades[0].reason_exit == "stop_loss"
    assert result.trades[0].exit_price == 99.0


def test_backtest_lifecycle_realizes_tp1_before_runner_stop() -> None:
    result = run_backtest_from_features(
        strategy=_DummyStrategy([SignalAction.BUY, SignalAction.HOLD]),
        features=_lifecycle_features(
            {
                "ts": pd.Timestamp("2026-01-01T00:15:00Z"),
                "open": 100.0,
                "high": 102.3,
                "low": 99.9,
                "close": 101.8,
                "atr": 2.0,
            },
            {
                "ts": pd.Timestamp("2026-01-01T00:20:00Z"),
                "open": 100.0,
                "high": 100.1,
                "low": 99.9,
                "close": 100.0,
                "atr": 2.0,
            },
        ),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=2,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        slippage_ratio=0.0,
        spread_ratio=0.0,
        max_hold_bars=5,
    )

    assert result.summary.total_trades == 1
    assert result.trades[0].reason_exit == "runner_stop"
    assert round(result.trades[0].exit_price, 2) == 100.88
    assert result.trades[0].net_pnl > 0.0
    assert result.summary.final_equity > 1000.0


def test_backtest_lifecycle_prefers_stop_loss_when_tp1_and_stop_hit_same_bar() -> None:
    result = run_backtest_from_features(
        strategy=_DummyStrategy([SignalAction.BUY, SignalAction.HOLD]),
        features=_lifecycle_features(
            {
                "ts": pd.Timestamp("2026-01-01T00:15:00Z"),
                "open": 100.0,
                "high": 102.3,
                "low": 97.0,
                "close": 100.0,
                "atr": 2.0,
            },
            {
                "ts": pd.Timestamp("2026-01-01T00:20:00Z"),
                "open": 100.0,
                "high": 100.1,
                "low": 99.9,
                "close": 100.0,
                "atr": 2.0,
            },
        ),
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=2,
        initial_equity=1000.0,
        max_position=1.0,
        fee_rate=0.0,
        slippage_ratio=0.0,
        spread_ratio=0.0,
        max_hold_bars=5,
    )

    assert result.summary.total_trades == 1
    assert result.trades[0].reason_exit == "stop_loss"
    assert round(result.trades[0].exit_price, 2) == 97.8


def _higher_features_with_bull_gate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ema_fast": 100.0,
                "ema_slow": 99.0,
                "rsi": 55.0,
                "adx": 22.0,
                "close": 100.0,
                "atr": 1.2,
            },
            {
                "ema_fast": 101.0,  # positive slope
                "ema_slow": 99.5,
                "rsi": 56.0,
                "adx": 22.0,
                "close": 101.0,
                "atr": 1.2,
            },
        ]
    )


def _features_with_breakout_then_tp1_then_runner_exit() -> pd.DataFrame:
    rows = []
    close = 100.0
    base_volume = 1000.0
    atr = 1.0
    for i in range(30):
        ts = pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=5 * i)
        prev_close = close
        close = prev_close + 0.05
        high = close + 0.3
        low = close - 0.3
        volume = base_volume
        rsi = 52.0
        ema_fast = 99.0 + i * 0.08
        ema_slow = 98.5 + i * 0.06
        if i == 20:
            # Make the latest bar a "breakout_long" template: close > prev_high and volume spike.
            close = prev_close + 1.2
            high = close + 0.2
            low = close - 0.25
            volume = base_volume * 1.6
            rsi = 56.0
            ema_fast = 100.0 + i * 0.08
            ema_slow = 99.0 + i * 0.06
        if i == 22:
            # Ensure the runner reaches tp1 (high spike) after entry.
            high = close + 4.0
        if i == 24:
            # Then retrace to hit runner stop (breakeven-ish).
            low = close - 4.0
        rows.append(
            {
                "ts": ts,
                "open": close - 0.05,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "volume_usd": volume * close,
                "rsi": rsi,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "atr": atr,
                "adx": 20.0,
                "macd": 0.0,
                "macd_signal": 0.0,
                "macd_hist": 0.0,
                "bb_high": close + 2.0,
                "bb_low": close - 2.0,
                "bb_width": 0.02,
            }
        )
    return pd.DataFrame(rows)


def test_backtest_uses_higher_timeframe_gate_and_staged_exit() -> None:
    result = run_backtest_from_features(
        strategy=Strategy(),
        features=_features_with_breakout_then_tp1_then_runner_exit(),
        higher_timeframe_features={"1H": _higher_features_with_bull_gate()},
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        warmup=20,
        max_position=1.0,
        leverage=5.0,
    )

    assert result.summary.total_trades == 1
    assert result.trades[0].reason_exit in {"take_profit_1", "runner_stop"}
