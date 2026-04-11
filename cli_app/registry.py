from __future__ import annotations

from .backtest_parser import register_backtest_commands
from .config_parser import register_config_commands
from .runtime_parser import register_runtime_commands
from .strategies_parser import register_strategy_commands

REGISTER_COMMANDS = (
    register_runtime_commands,
    register_config_commands,
    register_backtest_commands,
    register_strategy_commands,
)
