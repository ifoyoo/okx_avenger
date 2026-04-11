"""策略插件管理测试（开关 + 权重）。"""

from __future__ import annotations

import pandas as pd

from core.models import SignalAction
from core.strategy.core import ObjectiveSignal
from core.strategy.plugins import (
    SignalPluginDefinition,
    SignalPluginManager,
    format_plugin_snapshot,
    parse_enabled_plugins,
    parse_plugin_weights,
)


def test_parse_enabled_plugins() -> None:
    available = ["a", "b", "c"]
    assert parse_enabled_plugins("all", available) is None
    assert parse_enabled_plugins("", available) is None
    assert parse_enabled_plugins("a,c", available) == {"a", "c"}


def test_parse_plugin_weights() -> None:
    available = ["a", "b"]
    weights = parse_plugin_weights("a=1.2,b=0.7,c=2.0,bad", available)
    assert set(weights.keys()) == {"a", "b"}
    assert weights["a"] == 1.2
    assert weights["b"] == 0.7


class _DummyGenerator:
    def _sig_a(self, _features):
        return ObjectiveSignal("a", SignalAction.BUY, 0.5, "from-a")

    def _sig_b(self, _features):
        return ObjectiveSignal("b", SignalAction.SELL, 0.6, "from-b")


def test_signal_plugin_manager_enable_and_weight() -> None:
    manager = SignalPluginManager(
        enabled_raw="a",
        weights_raw="a=1.4,b=0.5",
        plugins=(
            SignalPluginDefinition(name="a", method_name="_sig_a"),
            SignalPluginDefinition(name="b", method_name="_sig_b"),
        ),
    )
    dummy = _DummyGenerator()
    df = pd.DataFrame([{"close": 1}])

    produced = manager.generate(dummy, df, None)

    assert len(produced) == 1
    signal = produced[0]
    assert signal.name == "a"
    assert abs(signal.confidence - 0.7) < 1e-9
    assert "权重x1.40" in signal.note


def test_format_plugin_snapshot() -> None:
    manager = SignalPluginManager(
        enabled_raw="a",
        weights_raw="a=1.3,b=0.9",
        plugins=(
            SignalPluginDefinition(name="a", method_name="_sig_a"),
            SignalPluginDefinition(name="b", method_name="_sig_b"),
        ),
    )
    text = format_plugin_snapshot(manager)
    assert "a(ON,w=1.30)" in text
    assert "b(OFF,w=0.90)" in text
