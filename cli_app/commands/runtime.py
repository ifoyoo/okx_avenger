from __future__ import annotations

import argparse

from cli_app.context import build_runtime
from cli_app.runtime_workflows import run_runtime_loop, run_runtime_once, show_runtime_status, sync_protection_orders


def cmd_once(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        return run_runtime_once(bundle, args)
    finally:
        bundle.close()


def cmd_run(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        return run_runtime_loop(bundle, args)
    finally:
        bundle.close()


def cmd_status(_: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        return show_runtime_status(bundle)
    finally:
        bundle.close()


def cmd_sync_protection(_: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        return sync_protection_orders(bundle)
    finally:
        bundle.close()
