"""配置校验与快照输出测试。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from config.settings import (
    AccountSettings,
    AppSettings,
    IntelSettings,
    LLMSettings,
    NotificationSettings,
    RuntimeSettings,
    StrategySettings,
    build_config_snapshot,
    dump_config_snapshot,
    find_unknown_env_keys,
)


def test_strategy_settings_reject_invalid_ratio() -> None:
    with pytest.raises(ValidationError):
        StrategySettings(BALANCE_USAGE_RATIO=1.2)


def test_strategy_settings_reject_invalid_upl_ratio() -> None:
    with pytest.raises(ValidationError):
        StrategySettings(DEFAULT_TAKE_PROFIT_UPL_RATIO=1.2)


def test_strategy_settings_expose_upl_ratio_defaults() -> None:
    assert StrategySettings.model_fields["default_take_profit_upl_ratio"].default == 0.2
    assert StrategySettings.model_fields["default_stop_loss_upl_ratio"].default == 0.1

    settings = StrategySettings(
        DEFAULT_TAKE_PROFIT_UPL_RATIO=0.34,
        DEFAULT_STOP_LOSS_UPL_RATIO=0.18,
    )

    assert settings.default_take_profit_upl_ratio == 0.34
    assert settings.default_stop_loss_upl_ratio == 0.18


def test_intel_settings_reject_invalid_threshold_order() -> None:
    with pytest.raises(ValidationError):
        IntelSettings(
            EVENT_GATE_DEGRADE_THRESHOLD=0.8,
            EVENT_GATE_BLOCK_THRESHOLD=0.7,
        )


def test_runtime_settings_do_not_expose_unused_app_metadata() -> None:
    assert RuntimeSettings.model_fields["execution_pending_order_ttl_minutes"].default == 60
    assert RuntimeSettings.model_fields["execution_allow_same_direction_scale_in"].default is True
    assert RuntimeSettings.model_fields["execution_same_direction_scale_in_multiplier"].default == 1.35

    runtime = RuntimeSettings(
        EXECUTION_PENDING_ORDER_TTL_MINUTES=30,
        EXECUTION_ALLOW_SAME_DIRECTION_SCALE_IN=True,
        EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER=3.0,
    )

    assert not hasattr(runtime, "app_version")
    assert not hasattr(runtime, "app_author")
    assert not hasattr(runtime, "protection_monitor_interval_seconds")
    assert runtime.execution_pending_order_ttl_minutes == 30
    assert runtime.execution_allow_same_direction_scale_in is True
    assert runtime.execution_same_direction_scale_in_multiplier == 3.0


def test_runtime_settings_reject_invalid_same_direction_scale_in_multiplier() -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER=0.5)


def test_settings_defaults_match_redesign(monkeypatch) -> None:
    # SettingsBase loads .env into the process environment (if present).
    # Ensure this test validates code defaults rather than local env overrides.
    for key in (
        "DEFAULT_LEVERAGE",
        "DEFAULT_MAX_POSITION",
        "EXECUTION_ALLOW_SAME_DIRECTION_SCALE_IN",
        "EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER",
        "RISK_DAILY_LOSS_LIMIT_PCT",
        "RISK_CONSECUTIVE_LOSS_LIMIT",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = RuntimeSettings()
    strategy = StrategySettings()

    assert strategy.default_leverage == 5.0
    assert settings.default_max_position == 0.02
    assert settings.execution_allow_same_direction_scale_in is True
    assert settings.execution_same_direction_scale_in_multiplier == 1.35
    assert strategy.risk_daily_loss_limit_pct == 0.02
    assert strategy.risk_consecutive_loss_limit == 3


def test_notification_settings_normalize_level() -> None:
    settings = NotificationSettings(NOTIFY_LEVEL="ORDERS")

    assert settings.level == "orders"


def test_build_and_dump_config_snapshot(tmp_path) -> None:
    runtime = RuntimeSettings(CONFIG_SNAPSHOT_PATH=str(tmp_path / "snapshot.json"))
    settings = AppSettings(
        account=AccountSettings(
            OKX_API_KEY="k",
            OKX_API_SECRET="s",
            OKX_PASSPHRASE="p",
        ),
        strategy=StrategySettings(STRATEGY_ARB_ENABLED=True),
        runtime=runtime,
        notification=NotificationSettings(),
        llm=LLMSettings(),
        intel=IntelSettings(),
    )

    snapshot = build_config_snapshot(settings)
    assert snapshot["account"]["okx_api_key_set"] is True
    assert "watchlist_mode" not in snapshot["runtime"]
    assert "auto_watchlist_size" not in snapshot["runtime"]

    path = dump_config_snapshot(settings, runtime.config_snapshot_path)
    assert path.exists()
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["strategy"]["strategy_arb_enabled"] is True


def test_find_unknown_env_keys_reports_unrecognized_keys(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OKX_API_KEY=k\nDEFAULT_LEVERGAE=10\n", encoding="utf-8")

    assert find_unknown_env_keys(env_path) == ("DEFAULT_LEVERGAE",)
