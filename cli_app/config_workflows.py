from __future__ import annotations

import argparse

from config.settings import dump_config_snapshot, get_settings

from cli_app.config_reporting import format_config_summary_lines
from cli_app.context import build_runtime


def _print_config_summary(settings) -> None:
    for line in format_config_summary_lines(settings):
        print(line)


def _print_snapshot_result(settings) -> None:
    try:
        snapshot_path = dump_config_snapshot(settings, settings.runtime.config_snapshot_path)
    except Exception as exc:
        print(f"⚠️ 配置快照写入失败: {exc}")
    else:
        print(f"- config_snapshot: {snapshot_path}")


def _run_api_check() -> int:
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


def run_config_check(args: argparse.Namespace) -> int:
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

    _print_config_summary(settings)
    _print_snapshot_result(settings)

    if not args.api_check:
        print("ℹ️ 未执行 API 联通性检查（加 --api-check 可检查）。")
        return 0

    return _run_api_check()
