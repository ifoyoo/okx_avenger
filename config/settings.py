"""Application configuration grouped by pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator

from .base import SettingsBase


class AccountSettings(SettingsBase):
    okx_api_key: str = Field(..., alias="OKX_API_KEY")
    okx_api_secret: str = Field(..., alias="OKX_API_SECRET")
    okx_passphrase: str = Field(..., alias="OKX_PASSPHRASE")
    okx_base_url: str = Field("https://www.okx.com", alias="OKX_BASE_URL")
    okx_td_mode: Optional[str] = Field(default=None, alias="OKX_TD_MODE")
    okx_force_pos_side: Optional[bool] = Field(default=None, alias="OKX_FORCE_POS_SIDE")
    http_timeout: float = Field(10.0, alias="HTTP_TIMEOUT")
    http_proxy: Optional[str] = Field(default=None, alias="HTTP_PROXY")

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


class AISettings(SettingsBase):
    provider: str = Field("deepseek", alias="AI_PROVIDER")

    deepseek_api_key: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field("deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_base_url: str = Field("https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL")

    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    azure_api_key: Optional[str] = Field(default=None, alias="AZURE_API_KEY")
    azure_endpoint: Optional[str] = Field(default=None, alias="AZURE_ENDPOINT")
    azure_deployment: Optional[str] = Field(default=None, alias="AZURE_DEPLOYMENT")
    azure_api_version: str = Field("2024-05-01-preview", alias="AZURE_API_VERSION")

    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-3-sonnet-20240229", alias="ANTHROPIC_MODEL")
    anthropic_base_url: str = Field("https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")

    moonshot_api_key: Optional[str] = Field(default=None, alias="MOONSHOT_API_KEY")
    moonshot_model: str = Field("moonshot-v1-8k", alias="MOONSHOT_MODEL")
    moonshot_base_url: str = Field("https://api.moonshot.cn/v1", alias="MOONSHOT_BASE_URL")

    qwen_api_key: Optional[str] = Field(default=None, alias="QWEN_API_KEY")
    qwen_model: str = Field("qwen-plus", alias="QWEN_MODEL")
    qwen_base_url: str = Field("https://dashscope.aliyuncs.com/compatible-mode/v1", alias="QWEN_BASE_URL")

    grok_api_key: Optional[str] = Field(default=None, alias="GROK_API_KEY")
    grok_model: str = Field("grok-beta", alias="GROK_MODEL")
    grok_base_url: str = Field("https://api.x.ai/v1", alias="GROK_BASE_URL")


class StrategySettings(SettingsBase):
    balance_usage_ratio: float = Field(0.7, alias="BALANCE_USAGE_RATIO")
    default_leverage: float = Field(1.0, alias="DEFAULT_LEVERAGE")
    default_take_profit_pct: float = Field(0.35, alias="DEFAULT_TAKE_PROFIT_PCT")
    default_stop_loss_pct: float = Field(0.2, alias="DEFAULT_STOP_LOSS_PCT")


class RuntimeSettings(SettingsBase):
    run_interval_minutes: int = Field(5, alias="RUN_INTERVAL_MINUTES")
    default_max_position: float = Field(0.002, alias="DEFAULT_MAX_POSITION")
    feature_limit: int = Field(150, alias="FEATURE_LIMIT")
    log_dir: str = Field("logs", alias="LOG_DIR")
    app_version: str = Field("0.1.0", alias="APP_VERSION")
    app_author: str = Field("余韵的左手（laofan_Fucker）", alias="APP_AUTHOR")
    watchlist_mode: str = Field("manual", alias="WATCHLIST_MODE")
    auto_watchlist_size: int = Field(5, alias="AUTO_WATCHLIST_SIZE")
    auto_watchlist_top_n: int = Field(10, alias="AUTO_WATCHLIST_TOP_N")
    auto_watchlist_refresh_hours: int = Field(24, alias="AUTO_WATCHLIST_REFRESH_HOURS")
    auto_watchlist_cache: str = Field("data/auto_watchlist.json", alias="AUTO_WATCHLIST_CACHE")
    auto_watchlist_timeframe: str = Field("5m", alias="AUTO_WATCHLIST_TIMEFRAME")
    auto_watchlist_higher_timeframes: str = Field("15m,1H", alias="AUTO_WATCHLIST_HIGHER_TIMEFRAMES")
    protection_monitor_interval_seconds: float = Field(
        30.0, alias="PROTECTION_MONITOR_INTERVAL_SECONDS"
    )


class NotificationSettings(SettingsBase):
    enabled: bool = Field(False, alias="NOTIFY_ENABLED")
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegram_api_url: str = Field("https://api.telegram.org", alias="TELEGRAM_API_URL")
    level: str = Field("critical", alias="NOTIFY_LEVEL")
    cooldown_seconds: float = Field(600.0, alias="NOTIFY_COOLDOWN_SECONDS")


@dataclass(frozen=True)
class AppSettings:
    account: AccountSettings
    ai: AISettings
    strategy: StrategySettings
    runtime: RuntimeSettings
    notification: NotificationSettings


@lru_cache()
def get_settings() -> AppSettings:
    return AppSettings(
        account=AccountSettings(),
        ai=AISettings(),
        strategy=StrategySettings(),
        runtime=RuntimeSettings(),
        notification=NotificationSettings(),
    )
