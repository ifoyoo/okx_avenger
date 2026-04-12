from __future__ import annotations


def _switch(enabled: object) -> str:
    return "on" if bool(enabled) else "off"


def format_config_summary_lines(settings) -> list[str]:
    lines = [
        "CONFIG READY",
        f"Account  base_url={settings.account.okx_base_url}",
        f"Runtime  interval={settings.runtime.run_interval_minutes}m leverage={settings.strategy.default_leverage}",
        f"Notify   {_switch(settings.notification.enabled)} level={settings.notification.level}",
    ]
    if settings.llm.enabled:
        lines.append(f"LLM      on model={settings.llm.model} base={settings.llm.api_base}")
    else:
        lines.append("LLM      off")
    if settings.intel.news_enabled:
        providers = settings.intel.news_providers or settings.intel.news_provider
        cg_key = "yes" if bool(settings.intel.coingecko_api_key) else "no"
        lines.append(
            f"Intel    on provider={settings.intel.news_provider} providers={providers} cg_key={cg_key}"
        )
    else:
        lines.append("Intel    off")
    return lines
