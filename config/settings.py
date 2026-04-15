"""Application configuration grouped by pipeline stages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import Field, field_validator, model_validator
from dotenv import dotenv_values

from .base import ENV_PATH, SettingsBase


class AccountSettings(SettingsBase):
    okx_api_key: str = Field(..., alias="OKX_API_KEY")
    okx_api_secret: str = Field(..., alias="OKX_API_SECRET")
    okx_passphrase: str = Field(..., alias="OKX_PASSPHRASE")
    okx_base_url: str = Field("https://www.okx.com", alias="OKX_BASE_URL")
    okx_td_mode: Optional[str] = Field(default=None, alias="OKX_TD_MODE")
    okx_force_pos_side: Optional[bool] = Field(default=None, alias="OKX_FORCE_POS_SIDE")
    http_timeout: float = Field(10.0, alias="HTTP_TIMEOUT")
    http_proxy: Optional[str] = Field(default=None, alias="HTTP_PROXY")
    http_max_retries: int = Field(2, alias="HTTP_MAX_RETRIES")
    http_retry_backoff_seconds: float = Field(0.4, alias="HTTP_RETRY_BACKOFF_SECONDS")

    @field_validator("okx_force_pos_side", mode="before")
    @classmethod
    def _normalize_force_pos_side(cls, value: Optional[str]) -> Optional[bool]:
        if value in ("", None):
            return None
        return value

    @field_validator("okx_td_mode", mode="before")
    @classmethod
    def _normalize_td_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @field_validator("http_max_retries", mode="after")
    @classmethod
    def _validate_http_max_retries(cls, value: int) -> int:
        if value < 0 or value > 8:
            raise ValueError("HTTP_MAX_RETRIES must be in [0, 8]")
        return value


class StrategySettings(SettingsBase):
    balance_usage_ratio: float = Field(0.7, alias="BALANCE_USAGE_RATIO")
    default_leverage: float = Field(1.0, alias="DEFAULT_LEVERAGE")
    default_take_profit_upl_ratio: float = Field(0.2, alias="DEFAULT_TAKE_PROFIT_UPL_RATIO")
    default_stop_loss_upl_ratio: float = Field(0.1, alias="DEFAULT_STOP_LOSS_UPL_RATIO")
    risk_daily_loss_limit: float = Field(0.0, alias="RISK_DAILY_LOSS_LIMIT")
    risk_daily_loss_limit_pct: float = Field(0.0, alias="RISK_DAILY_LOSS_LIMIT_PCT")
    risk_consecutive_loss_limit: int = Field(0, alias="RISK_CONSECUTIVE_LOSS_LIMIT")
    risk_consecutive_cooldown_minutes: int = Field(180, alias="RISK_CONSECUTIVE_COOLDOWN_MINUTES")
    risk_state_path: str = Field("data/risk_circuit_state.json", alias="RISK_STATE_PATH")
    strategy_signals_enabled: str = Field("all", alias="STRATEGY_SIGNALS_ENABLED")
    strategy_signal_weights: str = Field("", alias="STRATEGY_SIGNAL_WEIGHTS")
    strategy_arb_enabled: bool = Field(True, alias="STRATEGY_ARB_ENABLED")
    strategy_arb_same_side_boost: float = Field(0.08, alias="STRATEGY_ARB_SAME_SIDE_BOOST")
    strategy_arb_opposite_penalty: float = Field(0.18, alias="STRATEGY_ARB_OPPOSITE_PENALTY")
    strategy_arb_strong_conflict_ratio: float = Field(0.62, alias="STRATEGY_ARB_STRONG_CONFLICT_RATIO")
    strategy_arb_hold_confidence_cap: float = Field(0.35, alias="STRATEGY_ARB_HOLD_CONFIDENCE_CAP")
    strategy_arb_min_directional_signals: int = Field(2, alias="STRATEGY_ARB_MIN_DIRECTIONAL_SIGNALS")

    @field_validator(
        "balance_usage_ratio",
        "default_take_profit_upl_ratio",
        "default_stop_loss_upl_ratio",
        "risk_daily_loss_limit_pct",
        "strategy_arb_strong_conflict_ratio",
        "strategy_arb_hold_confidence_cap",
        mode="after",
    )
    @classmethod
    def _validate_unit_ratio(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("ratio fields must be between 0 and 1")
        return value

    @field_validator("default_leverage", mode="after")
    @classmethod
    def _validate_leverage(cls, value: float) -> float:
        if value < 1 or value > 125:
            raise ValueError("DEFAULT_LEVERAGE must be in [1, 125]")
        return value

    @field_validator(
        "risk_daily_loss_limit",
        "risk_consecutive_loss_limit",
        "risk_consecutive_cooldown_minutes",
        "strategy_arb_same_side_boost",
        "strategy_arb_opposite_penalty",
        "strategy_arb_min_directional_signals",
        mode="after",
    )
    @classmethod
    def _validate_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("value must be >= 0")
        return value


class RuntimeSettings(SettingsBase):
    run_interval_minutes: int = Field(5, alias="RUN_INTERVAL_MINUTES")
    default_max_position: float = Field(0.002, alias="DEFAULT_MAX_POSITION")
    feature_limit: int = Field(150, alias="FEATURE_LIMIT")
    feature_min_samples: int = Field(80, alias="FEATURE_MIN_SAMPLES")
    feature_indicator_overrides: str = Field("", alias="FEATURE_INDICATOR_OVERRIDES")
    log_dir: str = Field("logs", alias="LOG_DIR")
    data_staleness_seconds: int = Field(180, alias="DATA_STALENESS_SECONDS")
    execution_pending_timeout_seconds: float = Field(0.0, alias="EXECUTION_PENDING_TIMEOUT_SECONDS")
    execution_pending_order_ttl_minutes: int = Field(60, alias="EXECUTION_PENDING_ORDER_TTL_MINUTES")
    execution_allow_same_direction_scale_in: bool = Field(False, alias="EXECUTION_ALLOW_SAME_DIRECTION_SCALE_IN")
    execution_same_direction_scale_in_multiplier: float = Field(
        1.0,
        alias="EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER",
    )
    execution_reconcile_position: bool = Field(True, alias="EXECUTION_RECONCILE_POSITION")
    config_snapshot_path: str = Field("data/config_snapshot.json", alias="CONFIG_SNAPSHOT_PATH")
    runtime_heartbeat_path: str = Field("data/runtime_heartbeat.json", alias="RUNTIME_HEARTBEAT_PATH")

    @field_validator(
        "run_interval_minutes",
        "feature_min_samples",
        mode="after",
    )
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be > 0")
        return value

    @field_validator("execution_same_direction_scale_in_multiplier", mode="after")
    @classmethod
    def _validate_scale_in_multiplier(cls, value: float) -> float:
        if value < 1:
            raise ValueError("EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER must be >= 1")
        return value


class NotificationSettings(SettingsBase):
    enabled: bool = Field(False, alias="NOTIFY_ENABLED")
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegram_api_url: str = Field("https://api.telegram.org", alias="TELEGRAM_API_URL")
    level: str = Field("critical", alias="NOTIFY_LEVEL")
    cooldown_seconds: float = Field(600.0, alias="NOTIFY_COOLDOWN_SECONDS")

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_notification_level(cls, value: Optional[str]) -> str:
        level = str(value or "critical").strip().lower()
        if level not in {"critical", "orders", "all"}:
            return "critical"
        return level


class LLMSettings(SettingsBase):
    enabled: bool = Field(False, alias="LLM_ENABLED")
    provider: str = Field("openai_compatible", alias="LLM_PROVIDER")
    api_base: str = Field("https://api.openai.com/v1", alias="LLM_API_BASE")
    api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    model: str = Field("gpt-4o-mini", alias="LLM_MODEL")
    timeout_seconds: float = Field(8.0, alias="LLM_TIMEOUT_SECONDS")
    temperature: float = Field(0.1, alias="LLM_TEMPERATURE")
    max_tokens: int = Field(320, alias="LLM_MAX_TOKENS")
    influence_max_conf_delta: float = Field(0.15, alias="LLM_INFLUENCE_MAX_CONF_DELTA")
    influence_allow_reverse: bool = Field(False, alias="LLM_INFLUENCE_ALLOW_REVERSE")
    influence_allow_hold_to_direction: bool = Field(False, alias="LLM_INFLUENCE_ALLOW_HOLD_TO_DIRECTION")
    min_quality_score: float = Field(0.45, alias="LLM_MIN_QUALITY_SCORE")
    reject_missing_reason: bool = Field(True, alias="LLM_REJECT_MISSING_REASON")


class IntelSettings(SettingsBase):
    news_enabled: bool = Field(False, alias="NEWS_ENABLED")
    news_provider: str = Field("newsapi", alias="NEWS_PROVIDER")
    news_providers: str = Field("coingecko,newsapi", alias="NEWS_PROVIDERS")
    news_api_base: str = Field("https://newsapi.org/v2/everything", alias="NEWS_API_BASE")
    news_api_key: Optional[str] = Field(default=None, alias="NEWS_API_KEY")
    news_timeout_seconds: float = Field(6.0, alias="NEWS_TIMEOUT_SECONDS")
    news_limit: int = Field(10, alias="NEWS_LIMIT")
    news_window_hours: int = Field(24, alias="NEWS_WINDOW_HOURS")
    sentiment_enabled: bool = Field(True, alias="SENTIMENT_ENABLED")
    news_symbol_aliases: str = Field("", alias="NEWS_SYMBOL_ALIASES")
    news_coin_ids: str = Field("", alias="NEWS_COIN_IDS")
    news_source_whitelist: str = Field("", alias="NEWS_SOURCE_WHITELIST")
    news_source_blacklist: str = Field("", alias="NEWS_SOURCE_BLACKLIST")
    news_dedupe_window_minutes: int = Field(120, alias="NEWS_DEDUPE_WINDOW_MINUTES")
    coingecko_api_base: str = Field("https://pro-api.coingecko.com/api/v3", alias="COINGECKO_API_BASE")
    coingecko_api_key: Optional[str] = Field(default=None, alias="COINGECKO_API_KEY")
    coingecko_news_language: str = Field("en", alias="COINGECKO_NEWS_LANGUAGE")
    coingecko_news_type: str = Field("news", alias="COINGECKO_NEWS_TYPE")
    event_tag_enabled: bool = Field(True, alias="EVENT_TAG_ENABLED")
    event_gate_mode: str = Field("degrade", alias="EVENT_GATE_MODE")
    event_gate_degrade_threshold: float = Field(0.72, alias="EVENT_GATE_DEGRADE_THRESHOLD")
    event_gate_block_threshold: float = Field(0.9, alias="EVENT_GATE_BLOCK_THRESHOLD")
    event_gate_degrade_confidence_cap: float = Field(0.45, alias="EVENT_GATE_DEGRADE_CONFIDENCE_CAP")
    event_gate_degrade_size_ratio: float = Field(0.5, alias="EVENT_GATE_DEGRADE_SIZE_RATIO")

    @field_validator("event_gate_mode", mode="before")
    @classmethod
    def _normalize_event_gate_mode(cls, value: Optional[str]) -> str:
        mode = str(value or "degrade").strip().lower()
        if mode not in {"off", "degrade", "block"}:
            return "degrade"
        return mode

    @field_validator("coingecko_news_language", mode="before")
    @classmethod
    def _normalize_coingecko_news_language(cls, value: Optional[str]) -> str:
        return str(value or "en").strip().lower() or "en"

    @field_validator("coingecko_news_type", mode="before")
    @classmethod
    def _normalize_coingecko_news_type(cls, value: Optional[str]) -> str:
        news_type = str(value or "news").strip().lower() or "news"
        if news_type not in {"all", "news", "guides"}:
            return "news"
        return news_type

    @model_validator(mode="after")
    def _validate_event_threshold_relation(self) -> "IntelSettings":
        if self.event_gate_block_threshold < self.event_gate_degrade_threshold:
            raise ValueError("EVENT_GATE_BLOCK_THRESHOLD must be >= EVENT_GATE_DEGRADE_THRESHOLD")
        return self


@dataclass(frozen=True)
class AppSettings:
    account: AccountSettings
    strategy: StrategySettings
    runtime: RuntimeSettings
    notification: NotificationSettings
    llm: LLMSettings
    intel: IntelSettings


class UnknownEnvKeysError(ValueError):
    """Raised when the current .env file contains unsupported keys."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys
        super().__init__(f"Unknown .env keys: {', '.join(keys)}")


def _supported_env_keys() -> frozenset[str]:
    models = (
        AccountSettings,
        StrategySettings,
        RuntimeSettings,
        NotificationSettings,
        LLMSettings,
        IntelSettings,
    )
    keys: set[str] = set()
    for model in models:
        for field_name, field_info in model.model_fields.items():
            alias = field_info.alias or field_name
            key = str(alias).strip()
            if key:
                keys.add(key)
    return frozenset(keys)


SUPPORTED_ENV_KEYS = _supported_env_keys()


def find_unknown_env_keys(env_path: str | Path = ENV_PATH) -> tuple[str, ...]:
    path = Path(env_path)
    if not path.exists():
        return ()

    payload = dotenv_values(path)
    unknown = sorted(
        key.strip()
        for key in payload
        if key and key.strip() and key.strip() not in SUPPORTED_ENV_KEYS
    )
    return tuple(unknown)


def validate_env_file_keys(env_path: str | Path = ENV_PATH) -> None:
    unknown = find_unknown_env_keys(env_path)
    if unknown:
        raise UnknownEnvKeysError(unknown)


@lru_cache()
def get_settings() -> AppSettings:
    validate_env_file_keys()
    return AppSettings(
        account=AccountSettings(),
        strategy=StrategySettings(),
        runtime=RuntimeSettings(),
        notification=NotificationSettings(),
        llm=LLMSettings(),
        intel=IntelSettings(),
    )


def build_config_snapshot(settings: AppSettings) -> Dict[str, Any]:
    return {
        "account": {
            "okx_base_url": settings.account.okx_base_url,
            "okx_td_mode": settings.account.okx_td_mode,
            "http_timeout": settings.account.http_timeout,
            "http_max_retries": settings.account.http_max_retries,
            "http_retry_backoff_seconds": settings.account.http_retry_backoff_seconds,
            "http_proxy_set": bool(settings.account.http_proxy),
            "okx_api_key_set": bool(settings.account.okx_api_key),
            "okx_api_secret_set": bool(settings.account.okx_api_secret),
            "okx_passphrase_set": bool(settings.account.okx_passphrase),
        },
        "strategy": {
            "balance_usage_ratio": settings.strategy.balance_usage_ratio,
            "default_leverage": settings.strategy.default_leverage,
            "risk_daily_loss_limit": settings.strategy.risk_daily_loss_limit,
            "risk_daily_loss_limit_pct": settings.strategy.risk_daily_loss_limit_pct,
            "risk_consecutive_loss_limit": settings.strategy.risk_consecutive_loss_limit,
            "risk_consecutive_cooldown_minutes": settings.strategy.risk_consecutive_cooldown_minutes,
            "strategy_signals_enabled": settings.strategy.strategy_signals_enabled,
            "strategy_signal_weights": settings.strategy.strategy_signal_weights,
            "strategy_arb_enabled": settings.strategy.strategy_arb_enabled,
            "strategy_arb_same_side_boost": settings.strategy.strategy_arb_same_side_boost,
            "strategy_arb_opposite_penalty": settings.strategy.strategy_arb_opposite_penalty,
            "strategy_arb_strong_conflict_ratio": settings.strategy.strategy_arb_strong_conflict_ratio,
            "strategy_arb_hold_confidence_cap": settings.strategy.strategy_arb_hold_confidence_cap,
            "strategy_arb_min_directional_signals": settings.strategy.strategy_arb_min_directional_signals,
        },
        "runtime": {
            "run_interval_minutes": settings.runtime.run_interval_minutes,
            "default_max_position": settings.runtime.default_max_position,
            "feature_limit": settings.runtime.feature_limit,
            "feature_min_samples": settings.runtime.feature_min_samples,
            "data_staleness_seconds": settings.runtime.data_staleness_seconds,
            "execution_pending_timeout_seconds": settings.runtime.execution_pending_timeout_seconds,
            "execution_allow_same_direction_scale_in": settings.runtime.execution_allow_same_direction_scale_in,
            "execution_same_direction_scale_in_multiplier": settings.runtime.execution_same_direction_scale_in_multiplier,
            "execution_reconcile_position": settings.runtime.execution_reconcile_position,
            "config_snapshot_path": settings.runtime.config_snapshot_path,
            "runtime_heartbeat_path": settings.runtime.runtime_heartbeat_path,
        },
        "llm": {
            "enabled": settings.llm.enabled,
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "api_base": settings.llm.api_base,
            "api_key_set": bool(settings.llm.api_key),
        },
        "intel": {
            "news_enabled": settings.intel.news_enabled,
            "news_provider": settings.intel.news_provider,
            "news_providers": settings.intel.news_providers,
            "news_window_hours": settings.intel.news_window_hours,
            "news_symbol_aliases_set": bool(settings.intel.news_symbol_aliases),
            "news_coin_ids_set": bool(settings.intel.news_coin_ids),
            "coingecko_api_key_set": bool(settings.intel.coingecko_api_key),
            "event_tag_enabled": settings.intel.event_tag_enabled,
            "event_gate_mode": settings.intel.event_gate_mode,
            "event_gate_degrade_threshold": settings.intel.event_gate_degrade_threshold,
            "event_gate_block_threshold": settings.intel.event_gate_block_threshold,
        },
    }


def dump_config_snapshot(settings: AppSettings, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_config_snapshot(settings)
    with output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return output
