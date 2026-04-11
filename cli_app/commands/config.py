from __future__ import annotations

import argparse

from config.settings import dump_config_snapshot, get_settings

from cli_app.context import build_runtime


def cmd_config_check(args: argparse.Namespace) -> int:
    settings = get_settings()
    missing = []
    if not settings.account.okx_api_key:
        missing.append("OKX_API_KEY")
    if not settings.account.okx_api_secret:
        missing.append("OKX_API_SECRET")
    if not settings.account.okx_passphrase:
        missing.append("OKX_PASSPHRASE")
    if missing:
        print("❌ 缺少配置项:", ", ".join(missing))
        return 2
    print("✅ 本地配置字段完整。")
    print(f"- base_url: {settings.account.okx_base_url}")
    print(f"- watchlist_mode: {settings.runtime.watchlist_mode}")
    print(f"- run_interval_minutes: {settings.runtime.run_interval_minutes}")
    print(f"- default_leverage: {settings.strategy.default_leverage}")
    print(f"- llm_enabled: {settings.llm.enabled}")
    if settings.llm.enabled:
        print(f"- llm_model: {settings.llm.model}")
        print(f"- llm_api_base: {settings.llm.api_base}")
    print(f"- news_enabled: {settings.intel.news_enabled}")
    if settings.intel.news_enabled:
        print(f"- news_provider: {settings.intel.news_provider}")
        print(f"- news_providers: {settings.intel.news_providers or settings.intel.news_provider}")
        print(f"- news_api_base: {settings.intel.news_api_base}")
        print(f"- coingecko_api_base: {settings.intel.coingecko_api_base}")
        print(f"- coingecko_api_key_set: {bool(settings.intel.coingecko_api_key)}")
    try:
        snapshot_path = dump_config_snapshot(settings, settings.runtime.config_snapshot_path)
    except Exception as exc:
        print(f"⚠️ 配置快照写入失败: {exc}")
    else:
        print(f"- config_snapshot: {snapshot_path}")

    if not args.api_check:
        print("ℹ️ 未执行 API 联通性检查（加 --api-check 可检查）。")
        return 0

    bundle = build_runtime()
    try:
        try:
            _ = bundle.okx.get_account_config()
            _ = bundle.okx.instruments(inst_type="SWAP")
        except Exception as exc:
            print(f"❌ API 联通性检查失败: {exc}")
            return 1
        print("✅ API 联通性检查通过。")
        return 0
    finally:
        bundle.close()
