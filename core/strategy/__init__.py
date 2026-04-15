"""Strategy package exports (analysis + fusion logic)."""

from .core import (
    AnalysisView,
    ObjectiveSignal,
    ObjectiveSignalGenerator,
    Strategy,
    StrategyOutput,
)
from .positioning import PositionSizer, PositionSizerConfig
from .plugins import (
    SignalPluginDefinition,
    SignalPluginManager,
    build_signal_plugin_manager,
)
from .regime import HigherTimeframeGate, evaluate_higher_timeframe_gate

__all__ = [
    "AnalysisView",
    "HigherTimeframeGate",
    "ObjectiveSignal",
    "ObjectiveSignalGenerator",
    "PositionSizer",
    "PositionSizerConfig",
    "SignalPluginDefinition",
    "SignalPluginManager",
    "Strategy",
    "StrategyOutput",
    "build_signal_plugin_manager",
    "evaluate_higher_timeframe_gate",
]
