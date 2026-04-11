from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from dotenv import set_key

from config.settings import AppSettings, get_settings
from core.strategy.plugins import (
    build_signal_plugin_manager,
    parse_enabled_plugins,
    parse_plugin_weights,
)

ENV_FILE = Path(".env")


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
