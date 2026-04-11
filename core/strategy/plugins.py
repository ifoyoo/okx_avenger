"""策略插件管理：开关与权重配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from loguru import logger


DEFAULT_PLUGIN_ORDER: Tuple[str, ...] = (
    "volume_pressure",
    "volatility_breakout",
    "bull_trend",
    "ma_golden_cross",
    "shrink_pullback",
    "volume_breakout",
    "box_oscillation",
    "one_yang_three_yin",
)

DEFAULT_METHOD_MAP: Dict[str, str] = {
    "volume_pressure": "_volume_pressure_signal",
    "volatility_breakout": "_volatility_breakout_signal",
    "bull_trend": "_trend_regime_signal",
    "ma_golden_cross": "_ma_golden_cross_signal",
    "shrink_pullback": "_shrink_pullback_signal",
    "volume_breakout": "_price_volume_breakout_signal",
    "box_oscillation": "_box_oscillation_signal",
    "one_yang_three_yin": "_one_yang_three_yin_signal",
}


@dataclass(frozen=True)
class SignalPluginDefinition:
    name: str
    method_name: str


def parse_enabled_plugins(raw: Optional[str], available: Sequence[str]) -> Optional[Set[str]]:
    """解析开关配置。返回 None 表示全开。"""

    available_set = {item.strip() for item in available if str(item).strip()}
    text = str(raw or "").strip()
    if not text or text.lower() in {"all", "*"}:
        return None
    enabled: Set[str] = set()
    for part in text.split(","):
        name = part.strip()
        if not name:
            continue
        if name not in available_set:
            logger.warning("未知策略插件开关：{}（已忽略）", name)
            continue
        enabled.add(name)
    return enabled


def parse_plugin_weights(raw: Optional[str], available: Sequence[str]) -> Dict[str, float]:
    """解析权重配置：name=1.2,name2=0.8"""

    text = str(raw or "").strip()
    if not text:
        return {}
    available_set = {item.strip() for item in available if str(item).strip()}
    result: Dict[str, float] = {}
    for chunk in text.split(","):
        item = chunk.strip()
        if not item:
            continue
        if "=" not in item:
            logger.warning("策略权重配置格式错误：{}（应为 name=weight）", item)
            continue
        name, weight_text = item.split("=", 1)
        name = name.strip()
        if not name:
            continue
        if name not in available_set:
            logger.warning("未知策略权重：{}（已忽略）", name)
            continue
        try:
            weight = float(weight_text.strip())
        except (TypeError, ValueError):
            logger.warning("策略权重不是数字：{}={}", name, weight_text)
            continue
        result[name] = max(0.1, min(3.0, weight))
    return result


class SignalPluginManager:
    """执行策略插件并按权重调整置信度。"""

    def __init__(
        self,
        enabled_raw: Optional[str] = None,
        weights_raw: Optional[str] = None,
        plugins: Optional[Sequence[SignalPluginDefinition]] = None,
    ) -> None:
        plugin_defs = list(plugins) if plugins is not None else [
            SignalPluginDefinition(name=name, method_name=DEFAULT_METHOD_MAP[name])
            for name in DEFAULT_PLUGIN_ORDER
        ]
        self.plugins: Tuple[SignalPluginDefinition, ...] = tuple(plugin_defs)
        names = [plugin.name for plugin in self.plugins]
        self.enabled: Optional[Set[str]] = parse_enabled_plugins(enabled_raw, names)
        self.weights: Dict[str, float] = parse_plugin_weights(weights_raw, names)

    def generate(
        self,
        generator: Any,
        features: Any,
        higher_features: Optional[Dict[str, Any]],
    ) -> Tuple[Any, ...]:
        produced: List[Any] = []
        for plugin in self.plugins:
            if self.enabled is not None and plugin.name not in self.enabled:
                continue
            fn = getattr(generator, plugin.method_name, None)
            if fn is None:
                continue
            try:
                signal = fn(features)
            except TypeError:
                # 向后兼容：部分方法签名接收 (features, higher_features)
                signal = fn(features, higher_features)
            except Exception as exc:  # pragma: no cover
                logger.warning("执行策略插件失败 plugin={} err={}", plugin.name, exc)
                continue
            if signal is None:
                continue
            self.apply_weight(signal)
            produced.append(signal)
        return tuple(produced)

    def apply_weight(self, signal: Any) -> Any:
        name = str(getattr(signal, "name", "") or "")
        if not name:
            return signal
        weight = self.weights.get(name, 1.0)
        if abs(weight - 1.0) < 1e-9:
            return signal
        conf = float(getattr(signal, "confidence", 0.5) or 0.5)
        adjusted = max(0.1, min(1.0, conf * weight))
        setattr(signal, "confidence", adjusted)
        note = str(getattr(signal, "note", "") or "")
        setattr(signal, "note", f"{note} | 权重x{weight:.2f}".strip())
        return signal

    def status_rows(self) -> List[Tuple[str, bool, float]]:
        rows: List[Tuple[str, bool, float]] = []
        for plugin in self.plugins:
            enabled = self.enabled is None or plugin.name in self.enabled
            weight = self.weights.get(plugin.name, 1.0)
            rows.append((plugin.name, enabled, weight))
        return rows


def build_signal_plugin_manager(settings: Optional[Any] = None) -> SignalPluginManager:
    """从 settings 中构建插件管理器。"""

    enabled_raw: Optional[str] = None
    weights_raw: Optional[str] = None
    if settings is not None:
        strategy_settings = getattr(settings, "strategy", None)
        if strategy_settings is not None:
            enabled_raw = getattr(strategy_settings, "strategy_signals_enabled", None)
            weights_raw = getattr(strategy_settings, "strategy_signal_weights", None)
    return SignalPluginManager(enabled_raw=enabled_raw, weights_raw=weights_raw)


def format_plugin_snapshot(manager: SignalPluginManager) -> str:
    """格式化策略插件状态，便于日志/CLI 展示。"""

    parts: List[str] = []
    for name, enabled, weight in manager.status_rows():
        status = "ON" if enabled else "OFF"
        parts.append(f"{name}({status},w={weight:.2f})")
    return ", ".join(parts)


__all__ = [
    "SignalPluginDefinition",
    "SignalPluginManager",
    "build_signal_plugin_manager",
    "format_plugin_snapshot",
    "parse_enabled_plugins",
    "parse_plugin_weights",
]
