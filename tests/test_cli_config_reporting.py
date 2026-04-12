"""CLI config 输出格式化测试。"""

from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace


def _load_reporting():
    assert importlib.util.find_spec("cli_app.config_reporting") is not None
    module = importlib.import_module("cli_app.config_reporting")
    assert hasattr(module, "format_config_summary_lines")
    return module


def _settings(*, llm_enabled=False, news_enabled=False):
    return SimpleNamespace(
        account=SimpleNamespace(okx_base_url="https://www.okx.com"),
        runtime=SimpleNamespace(run_interval_minutes=5),
        strategy=SimpleNamespace(default_leverage=3),
        notification=SimpleNamespace(enabled=False, level="critical"),
        llm=SimpleNamespace(enabled=llm_enabled, model="gpt-x", api_base="https://api.example.com"),
        intel=SimpleNamespace(
            news_enabled=news_enabled,
            news_provider="newsapi",
            news_providers="newsapi,coingecko",
            news_api_base="https://news.example.com",
            coingecko_api_base="https://cg.example.com",
            coingecko_api_key="cg-key",
        ),
    )


def test_config_reporting_module_exists() -> None:
    _load_reporting()


def test_format_config_summary_lines_without_optional_sections() -> None:
    reporting = _load_reporting()
    lines = reporting.format_config_summary_lines(_settings())

    assert lines == [
        "CONFIG READY",
        "Account  base_url=https://www.okx.com",
        "Runtime  interval=5m leverage=3",
        "Notify   off level=critical",
        "LLM      off",
        "Intel    off",
    ]


def test_format_config_summary_lines_with_llm_and_news_sections() -> None:
    reporting = _load_reporting()
    lines = reporting.format_config_summary_lines(_settings(llm_enabled=True, news_enabled=True))

    assert "Notify   off level=critical" in lines
    assert "LLM      on model=gpt-x base=https://api.example.com" in lines
    assert "Intel    on provider=newsapi providers=newsapi,coingecko cg_key=yes" in lines
