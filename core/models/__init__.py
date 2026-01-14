"""项目核心数据模型."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class ProtectionRule:
    """配置层的止盈止损规则."""

    mode: str = "disabled"
    value: float = 0.0
    trigger_type: str = "last"
    order_type: str = "market"

    def is_active(self) -> bool:
        try:
            value = float(self.value)
        except (TypeError, ValueError):
            value = 0.0
        return self.mode not in ("disabled", "off", "none", "", None) and value > 0


@dataclass
class ProtectionSettings:
    """聚合止盈止损配置."""

    take_profit: ProtectionRule
    stop_loss: ProtectionRule


@dataclass
class ProtectionTarget:
    """标准化的止盈/止损触发信息，优先使用比例驱动委托."""

    trigger_ratio: Optional[float] = None
    trigger_px: Optional[float] = None
    order_px: Optional[float] = None
    trigger_type: str = "last"
    order_type: str = "market"
    order_kind: str = "condition"
    mode: Optional[str] = None

    def has_ratio(self) -> bool:
        return self.trigger_ratio is not None and abs(self.trigger_ratio) > 0

    def has_price(self) -> bool:
        return self.trigger_px is not None and self.trigger_px > 0


@dataclass
class TradeProtection:
    """附着在 TradeSignal 上的止盈/止损方案."""

    take_profit: Optional[ProtectionTarget] = None
    stop_loss: Optional[ProtectionTarget] = None


@dataclass
class TradeSignal:
    """策略输出的交易信号."""

    action: SignalAction
    confidence: float
    reason: str
    size: float = 0.0
    protection: Optional[TradeProtection] = None


@dataclass
class StrategyContext:
    """策略运算所需的上下文."""

    inst_id: str
    timeframe: str
    dry_run: bool = True
    max_position: float = 0.0
    leverage: float = 1.0
    risk_note: Optional[str] = None
    higher_timeframes: Tuple[str, ...] = ()
    account_equity: Optional[float] = None
    available_balance: Optional[float] = None
    protection: Optional[ProtectionSettings] = None
    enable_analysis: bool = True
    analysis_weight: float = 0.5
