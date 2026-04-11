from __future__ import annotations

import argparse

from cli_app.strategy_workflows import run_strategy_action


def cmd_strategies(args: argparse.Namespace) -> int:
    return run_strategy_action(args)
