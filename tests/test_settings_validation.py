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


def test_intel_settings_reject_invalid_threshold_order() -> None:
    with pytest.raises(ValidationError):
        IntelSettings(
            EVENT_GATE_DEGRADE_THRESHOLD=0.8,
            EVENT_GATE_BLOCK_THRESHOLD=0.7,
        )


def test_runtime_settings_do_not_expose_unused_app_metadata() -> None:
    runtime = RuntimeSettings()

    assert not hasattr(runtime, "app_version")
    assert not hasattr(runtime, "app_author")
    assert not hasattr(runtime, "protection_monitor_interval_seconds")


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
