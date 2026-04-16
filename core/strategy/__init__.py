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
from .templates import EntryTemplateMatch, evaluate_entry_template
from .lifecycle import (
    LifecyclePlan,
    LifecycleStage,
    build_lifecycle_plan,
    evaluate_lifecycle_stage,
)

__all__ = [
    "AnalysisView",
    "EntryTemplateMatch",
    "HigherTimeframeGate",
    "LifecyclePlan",
    "LifecycleStage",
    "ObjectiveSignal",
    "ObjectiveSignalGenerator",
    "PositionSizer",
    "PositionSizerConfig",
    "SignalPluginDefinition",
    "SignalPluginManager",
    "Strategy",
    "StrategyOutput",
    "build_lifecycle_plan",
    "build_signal_plugin_manager",
    "evaluate_entry_template",
    "evaluate_higher_timeframe_gate",
    "evaluate_lifecycle_stage",
]
