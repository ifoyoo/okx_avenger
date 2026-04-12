from __future__ import annotations


def format_config_summary_lines(settings) -> list[str]:
    lines = [
        "✅ 本地配置字段完整。",
        f"- base_url: {settings.account.okx_base_url}",
        f"- run_interval_minutes: {settings.runtime.run_interval_minutes}",
        f"- default_leverage: {settings.strategy.default_leverage}",
        f"- llm_enabled: {settings.llm.enabled}",
    ]
    if settings.llm.enabled:
        lines.append(f"- llm_model: {settings.llm.model}")
        lines.append(f"- llm_api_base: {settings.llm.api_base}")
    lines.append(f"- news_enabled: {settings.intel.news_enabled}")
    if settings.intel.news_enabled:
        lines.append(f"- news_provider: {settings.intel.news_provider}")
        lines.append(f"- news_providers: {settings.intel.news_providers or settings.intel.news_provider}")
        lines.append(f"- news_api_base: {settings.intel.news_api_base}")
        lines.append(f"- coingecko_api_base: {settings.intel.coingecko_api_base}")
        lines.append(f"- coingecko_api_key_set: {bool(settings.intel.coingecko_api_key)}")
    return lines
