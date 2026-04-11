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


def _print_enabled_update(value: str) -> None:
    print(f"✅ STRATEGY_SIGNALS_ENABLED={value}")
    _print_strategies(get_settings())


def _print_weight_update(value: str) -> None:
    print(f"✅ STRATEGY_SIGNAL_WEIGHTS={value}")
    _print_strategies(get_settings())


def run_strategy_action(args: argparse.Namespace) -> int:
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
        _print_enabled_update(value)
        return 0

    if action == "enable":
        targets, unknown = _normalize_names(args.names, names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        enabled = _current_enabled_set(settings, names)
        value = _save_enabled_config(None if enabled is None else enabled.union(targets), names)
        _refresh_settings_cache()
        _print_enabled_update(value)
        return 0

    if action == "disable":
        targets, unknown = _normalize_names(args.names, names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        enabled = _current_enabled_set(settings, names)
        current_enabled = set(names) if enabled is None else set(enabled)
        current_enabled.difference_update(targets)
        value = _save_enabled_config(current_enabled, names)
        _refresh_settings_cache()
        _print_enabled_update(value)
        return 0

    if action == "set-weight":
        targets, unknown = _normalize_names([args.name], names)
        if unknown:
            print("❌ 未知策略：", ", ".join(unknown))
            return 2
        weights = _current_weight_map(settings, names)
        weights[targets[0]] = max(0.1, min(3.0, float(args.weight)))
        value = _save_weight_config(weights, names)
        _refresh_settings_cache()
        _print_weight_update(value)
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
        _print_weight_update(value)
        return 0

    if action == "clear-weights":
        value = _save_weight_config({}, names)
        _refresh_settings_cache()
        _print_weight_update(value)
        return 0

    print(f"❌ 不支持的操作: {action}")
    return 2
