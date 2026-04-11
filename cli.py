"""简洁 CLI 入口：支持 run / once / status / config-check / strategies / backtest."""

from __future__ import annotations

from typing import Iterable, Optional

from cli_app import build_parser as _build_parser

build_parser = _build_parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
