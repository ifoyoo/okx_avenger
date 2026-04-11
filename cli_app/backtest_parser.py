from __future__ import annotations

from cli_app.commands.backtest import cmd_backtest_report, cmd_backtest_run, cmd_backtest_tune
from cli_app.runtime_helpers import DEFAULT_TIMEFRAME


def register_backtest_commands(subparsers) -> None:
    p_backtest = subparsers.add_parser("backtest", help="运行或查看策略回测")
    p_backtest_sub = p_backtest.add_subparsers(dest="backtest_action", required=True)

    p_backtest_run = p_backtest_sub.add_parser("run", help="执行回测并保存结果")
    p_backtest_run.add_argument("--inst", help="指定单个交易对，例如 BTC-USDT-SWAP")
    p_backtest_run.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="K线周期，默认 5m")
    p_backtest_run.add_argument(
        "--higher-timeframes",
        default="1H",
        help="保留参数（与 once/run 对齐），回测暂不使用",
    )
    p_backtest_run.add_argument("--max-position", type=float, default=0.0, help="单标的最大下单量")
    p_backtest_run.add_argument("--limit", type=int, default=600, help="回测K线数量，默认 600")
    p_backtest_run.add_argument("--warmup", type=int, default=120, help="预热K线数量，默认 120")
    p_backtest_run.add_argument("--initial-equity", type=float, default=10_000.0, help="初始资金，默认 10000")
    p_backtest_run.add_argument("--fee-rate", type=float, default=0.0005, help="单边手续费率，默认 0.0005")
    p_backtest_run.add_argument("--slippage-ratio", type=float, default=0.0002, help="滑点比例，默认 0.0002")
    p_backtest_run.add_argument("--spread-ratio", type=float, default=0.0001, help="点差比例，默认 0.0001")
    p_backtest_run.add_argument("--max-hold-bars", type=int, default=48, help="最长持仓K线数，默认 48")
    p_backtest_run.set_defaults(func=cmd_backtest_run)

    p_backtest_report = p_backtest_sub.add_parser("report", help="查看回测报告")
    p_backtest_report.add_argument("--file", help="指定报告文件，默认 data/backtests/latest.json")
    p_backtest_report.add_argument("--inst", help="仅查看指定交易对")
    p_backtest_report.add_argument("--show-trades", action="store_true", help="展示成交明细")
    p_backtest_report.add_argument("--max-trades", type=int, default=10, help="每个标的最多展示成交条数")
    p_backtest_report.set_defaults(func=cmd_backtest_report)

    p_backtest_tune = p_backtest_sub.add_parser("tune", help="基于回测推荐策略权重")
    p_backtest_tune.add_argument("--inst", help="指定单个交易对，例如 BTC-USDT-SWAP")
    p_backtest_tune.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="K线周期，默认 5m")
    p_backtest_tune.add_argument(
        "--higher-timeframes",
        default="1H",
        help="保留参数（与 once/run 对齐），调参暂不使用",
    )
    p_backtest_tune.add_argument("--max-position", type=float, default=0.0, help="单标的最大下单量")
    p_backtest_tune.add_argument("--limit", type=int, default=800, help="回测K线数量，默认 800")
    p_backtest_tune.add_argument("--warmup", type=int, default=120, help="预热K线数量，默认 120")
    p_backtest_tune.add_argument("--initial-equity", type=float, default=10_000.0, help="初始资金，默认 10000")
    p_backtest_tune.add_argument("--fee-rate", type=float, default=0.0005, help="单边手续费率，默认 0.0005")
    p_backtest_tune.add_argument("--slippage-ratio", type=float, default=0.0002, help="滑点比例，默认 0.0002")
    p_backtest_tune.add_argument("--spread-ratio", type=float, default=0.0001, help="点差比例，默认 0.0001")
    p_backtest_tune.add_argument("--max-hold-bars", type=int, default=48, help="最长持仓K线数，默认 48")
    p_backtest_tune.add_argument("--apply", action="store_true", help="把推荐权重写入 .env")
    p_backtest_tune.set_defaults(func=cmd_backtest_tune)
