from __future__ import annotations

import argparse

from cli_app.config_workflows import run_config_check


def cmd_config_check(args: argparse.Namespace) -> int:
    return run_config_check(args)
