from __future__ import annotations

import argparse

from cli_app.context import build_runtime
from cli_app.backtest_workflows import report_backtest, run_backtest_for_bundle, tune_backtest_for_bundle


def cmd_backtest_run(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        return run_backtest_for_bundle(bundle, args)
    finally:
        bundle.close()


def cmd_backtest_report(args: argparse.Namespace) -> int:
    return report_backtest(args)


def cmd_backtest_tune(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        return tune_backtest_for_bundle(bundle, args)
    finally:
        bundle.close()
