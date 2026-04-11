from __future__ import annotations

import argparse

from .registry import REGISTER_COMMANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="okx", description="OKX 自动交易 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for register in REGISTER_COMMANDS:
        register(sub)
    return parser
