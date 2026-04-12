from __future__ import annotations

from cli_app.commands.runtime import cmd_once, cmd_run, cmd_status
from cli_app.runtime_helpers import DEFAULT_LIMIT, DEFAULT_TIMEFRAME
from config.settings import get_settings


def _runtime_limit_default() -> int:
    try:
        return max(1, int(get_settings().runtime.feature_limit))
    except Exception:
        return DEFAULT_LIMIT


def _add_common_run_args(parser) -> None:
    parser.add_argument("--inst", help="指定单个交易对，例如 BTC-USDT-SWAP")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="K线周期，默认 5m")
    parser.add_argument(
        "--higher-timeframes",
        default="1H",
        help="高阶周期，逗号分隔，例如 1H,4H",
    )
    parser.add_argument("--max-position", type=float, default=0.0, help="单标的最大下单量（覆盖 watchlist）")
    parser.add_argument("--limit", type=int, default=_runtime_limit_default(), help="K线数量，默认读取 FEATURE_LIMIT")
    parser.add_argument("--dry-run", action="store_true", help="仿真模式，不实际下单")


def register_runtime_commands(subparsers) -> None:
    p_once = subparsers.add_parser("once", help="执行一轮扫描")
    _add_common_run_args(p_once)
    p_once.set_defaults(func=cmd_once)

    p_run = subparsers.add_parser("run", help="循环扫描（常驻）")
    _add_common_run_args(p_run)
    p_run.add_argument("--interval-minutes", type=int, default=0, help="扫描间隔（分钟）")
    p_run.set_defaults(func=cmd_run)

    p_status = subparsers.add_parser("status", help="查看账户、持仓、watchlist 状态")
    p_status.set_defaults(func=cmd_status)
