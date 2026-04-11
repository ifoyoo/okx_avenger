from __future__ import annotations

import argparse

from config.settings import get_settings

from cli_app.strategy_config_helpers import (
    _current_enabled_set,
    _current_weight_map,
    _normalize_names,
    _print_strategies,
    _refresh_settings_cache,
    _save_enabled_config,
    _save_weight_config,
    _strategy_names_from_settings,
)


def cmd_strategies(args: argparse.Namespace) -> int:
    _refresh_settings_cache()
    settings = get_settings()
    names = _strategy_names_from_settings(settings)
    action = args.strategy_action

    if action == "list":
        _print_strategies(settings, enabled_only=bool(getattr(args, "enabled_only", False)))
        return 0

    if action == "enable-all":
        value = _save_enabled_config(None, names)
        _refresh_settings_cache()
        print(f"✅ STRATEGY_SIGNALS_ENABLED={value}")
        _print_strategies(get_settings())
        return 0

    if action == "enable":
        targets, unknown = _normalize_names(args.names, names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        enabled = _current_enabled_set(settings, names)
        if enabled is None:
            value = _save_enabled_config(None, names)
        else:
            enabled.update(targets)
            value = _save_enabled_config(enabled, names)
        _refresh_settings_cache()
        print(f"✅ STRATEGY_SIGNALS_ENABLED={value}")
        _print_strategies(get_settings())
        return 0

    if action == "disable":
        targets, unknown = _normalize_names(args.names, names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        enabled = _current_enabled_set(settings, names)
        if enabled is None:
            enabled = set(names)
        enabled.difference_update(targets)
        value = _save_enabled_config(enabled, names)
        _refresh_settings_cache()
        print(f"✅ STRATEGY_SIGNALS_ENABLED={value}")
        _print_strategies(get_settings())
        return 0

    if action == "set-weight":
        targets, unknown = _normalize_names([args.name], names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        name = targets[0]
        weight = max(0.1, min(3.0, float(args.weight)))
        weights = _current_weight_map(settings, names)
        weights[name] = weight
        value = _save_weight_config(weights, names)
        _refresh_settings_cache()
        print(f"✅ STRATEGY_SIGNAL_WEIGHTS={value}")
        _print_strategies(get_settings())
        return 0

    if action == "reset-weight":
        targets, unknown = _normalize_names(args.names, names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        weights = _current_weight_map(settings, names)
        for name in targets:
            weights.pop(name, None)
        value = _save_weight_config(weights, names)
        _refresh_settings_cache()
        print(f"✅ STRATEGY_SIGNAL_WEIGHTS={value}")
        _print_strategies(get_settings())
        return 0

    if action == "clear-weights":
        value = _save_weight_config({}, names)
        _refresh_settings_cache()
        print(f"✅ STRATEGY_SIGNAL_WEIGHTS={value}")
        _print_strategies(get_settings())
        return 0

    print(f"❌ 不支持的操作: {action}")
    return 2


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
