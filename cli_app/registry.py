from __future__ import annotations

from .commands.backtest import register_backtest_commands
from .commands.config import register_config_commands
from .commands.runtime import register_runtime_commands
from .commands.strategies import register_strategy_commands

REGISTER_COMMANDS = (
    register_runtime_commands,
    register_config_commands,
    register_backtest_commands,
    register_strategy_commands,
)
