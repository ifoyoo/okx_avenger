from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from dotenv import set_key

from config.settings import AppSettings, get_settings
from core.strategy.plugins import (
    build_signal_plugin_manager,
    parse_enabled_plugins,
    parse_plugin_weights,
)

from cli_app.helpers import ENV_FILE


def _refresh_settings_cache() -> None:
    clear = getattr(get_settings, "cache_clear", None)
    if callable(clear):
        clear()


def _strategy_names_from_settings(settings: AppSettings) -> List[str]:
    manager = build_signal_plugin_manager(settings)
    return [name for name, _enabled, _weight in manager.status_rows()]


def _normalize_names(input_names: Sequence[str], available: Sequence[str]) -> Tuple[List[str], List[str]]:
    normalized: List[str] = []
    unknown: List[str] = []
    available_set = {item.strip() for item in available if str(item).strip()}
    for raw in input_names:
        name = str(raw or "").strip()
        if not name:
            continue
        if name not in available_set:
            unknown.append(name)
            continue
        if name not in normalized:
            normalized.append(name)
    return normalized, unknown


def _ordered_join(names: Set[str], ordered: Sequence[str]) -> str:
    rows = [item for item in ordered if item in names]
    return ",".join(rows)


def _current_enabled_set(settings: AppSettings, names: Sequence[str]) -> Optional[Set[str]]:
    return parse_enabled_plugins(settings.strategy.strategy_signals_enabled, names)


def _current_weight_map(settings: AppSettings, names: Sequence[str]) -> Dict[str, float]:
    return parse_plugin_weights(settings.strategy.strategy_signal_weights, names)


def _save_env_key(key: str, value: str) -> None:
    if not ENV_FILE.exists():
        ENV_FILE.touch()
    set_key(str(ENV_FILE), key, value, quote_mode="never")


def _save_enabled_config(enabled: Optional[Set[str]], names: Sequence[str]) -> str:
    all_set = set(names)
    if enabled is None or enabled == all_set:
        value = "all"
    else:
        value = _ordered_join(enabled, names)
    _save_env_key("STRATEGY_SIGNALS_ENABLED", value)
    return value


def _save_weight_config(weights: Dict[str, float], names: Sequence[str]) -> str:
    items = []
    for name in names:
        if name not in weights:
            continue
        items.append(f"{name}={weights[name]:.2f}")
    value = ",".join(items)
    _save_env_key("STRATEGY_SIGNAL_WEIGHTS", value)
    return value


def _print_strategies(settings: AppSettings, *, enabled_only: bool = False) -> None:
    manager = build_signal_plugin_manager(settings)
    rows = manager.status_rows()
    print("=== Strategies ===")
    print(f"{'name':<24} {'enabled':<8} {'weight':<8}")
    print("-" * 44)
    for name, enabled, weight in rows:
        if enabled_only and not enabled:
            continue
        print(f"{name:<24} {('yes' if enabled else 'no'):<8} {weight:<8.2f}")


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
