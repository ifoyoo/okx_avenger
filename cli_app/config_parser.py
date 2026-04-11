from __future__ import annotations

from cli_app.commands.config import cmd_config_check


def register_config_commands(subparsers) -> None:
    parser = subparsers.add_parser("config-check", help="检查配置")
    parser.add_argument("--api-check", action="store_true", help="执行 API 联通性检查")
    parser.set_defaults(func=cmd_config_check)
