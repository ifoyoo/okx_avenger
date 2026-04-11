from __future__ import annotations

from cli_app.commands.strategies import cmd_strategies


def register_strategy_commands(subparsers) -> None:
    p_strategies = subparsers.add_parser("strategies", help="查看或修改策略插件开关与权重")
    p_strategies_sub = p_strategies.add_subparsers(dest="strategy_action", required=True)

    p_strat_list = p_strategies_sub.add_parser("list", help="显示策略状态")
    p_strat_list.add_argument("--enabled-only", action="store_true", help="仅显示已启用策略")
    p_strat_list.set_defaults(func=cmd_strategies)

    p_strat_enable = p_strategies_sub.add_parser("enable", help="启用指定策略")
    p_strat_enable.add_argument("names", nargs="+", help="策略名，可传多个")
    p_strat_enable.set_defaults(func=cmd_strategies)

    p_strat_disable = p_strategies_sub.add_parser("disable", help="禁用指定策略")
    p_strat_disable.add_argument("names", nargs="+", help="策略名，可传多个")
    p_strat_disable.set_defaults(func=cmd_strategies)

    p_strat_enable_all = p_strategies_sub.add_parser("enable-all", help="启用全部策略")
    p_strat_enable_all.set_defaults(func=cmd_strategies)

    p_strat_set_weight = p_strategies_sub.add_parser("set-weight", help="设置策略权重")
    p_strat_set_weight.add_argument("name", help="策略名")
    p_strat_set_weight.add_argument("weight", type=float, help="权重（0.1~3.0）")
    p_strat_set_weight.set_defaults(func=cmd_strategies)

    p_strat_reset_weight = p_strategies_sub.add_parser("reset-weight", help="重置指定策略权重")
    p_strat_reset_weight.add_argument("names", nargs="+", help="策略名，可传多个")
    p_strat_reset_weight.set_defaults(func=cmd_strategies)

    p_strat_clear_weights = p_strategies_sub.add_parser("clear-weights", help="清空所有权重")
    p_strat_clear_weights.set_defaults(func=cmd_strategies)
