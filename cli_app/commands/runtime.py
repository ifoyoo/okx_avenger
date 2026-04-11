from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from loguru import logger

from cli_app.context import build_runtime
from cli_app.runtime_execution import log_strategy_snapshot, run_runtime_cycle
from cli_app.runtime_helpers import (
    _read_runtime_heartbeat,
    _safe_account_snapshot,
    _write_runtime_heartbeat,
)
from cli_app.runtime_status_helpers import (
    _format_account_lines,
    _format_heartbeat_lines,
    _format_position_lines,
    _format_watchlist_lines,
)


def cmd_once(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
    try:
        _write_runtime_heartbeat(path=heartbeat_path, status="running", cycle=1)
        log_strategy_snapshot(bundle)
        exit_code = run_runtime_cycle(bundle, args)
        _write_runtime_heartbeat(path=heartbeat_path, status="idle", cycle=1, exit_code=exit_code)
        return exit_code
    except Exception as exc:
        _write_runtime_heartbeat(path=heartbeat_path, status="error", cycle=1, exit_code=2, detail=str(exc))
        raise
    finally:
        bundle.close()


def cmd_run(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
    interval = max(1, int(args.interval_minutes or bundle.settings.runtime.run_interval_minutes))
    logger.info("进入循环模式，间隔 {} 分钟（Ctrl+C 退出）", interval)
    log_strategy_snapshot(bundle)
    cycle = 0
    try:
        while True:
            cycle += 1
            started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info("===== 新一轮扫描开始 {} =====", started)
            _write_runtime_heartbeat(path=heartbeat_path, status="running", cycle=cycle)
            exit_code = run_runtime_cycle(bundle, args)
            state = "idle" if exit_code == 0 else "error"
            _write_runtime_heartbeat(path=heartbeat_path, status=state, cycle=cycle, exit_code=exit_code)
            logger.info("===== 本轮结束，休眠 {} 分钟 =====", interval)
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        _write_runtime_heartbeat(path=heartbeat_path, status="stopped", cycle=cycle, exit_code=0)
        logger.info("收到中断信号，退出。")
        return 0
    except Exception as exc:
        _write_runtime_heartbeat(path=heartbeat_path, status="error", cycle=cycle, exit_code=2, detail=str(exc))
        raise
    finally:
        bundle.close()


def cmd_status(_: argparse.Namespace) -> int:
    bundle = build_runtime()
    try:
        account_snapshot = _safe_account_snapshot(bundle.engine)
        print("=== Account ===")
        for row in _format_account_lines(account_snapshot):
            print(row)

        print("\n=== Watchlist ===")
        entries = bundle.watchlist_manager.get_watchlist(account_snapshot)
        for row in _format_watchlist_lines(entries):
            print(row)

        print("\n=== Position ===")
        try:
            positions = bundle.okx.get_positions(inst_type="SWAP").get("data") or []
        except Exception as exc:
            print(f"query failed: {exc}")
            return 1
        if not positions:
            print("(no positions)")
        else:
            for row in _format_position_lines(positions):
                print(row)
        heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
        heartbeat = _read_runtime_heartbeat(heartbeat_path)
        print("\n=== Runtime Heartbeat ===")
        for row in _format_heartbeat_lines(heartbeat_path, heartbeat):
            print(row)
        return 0
    finally:
        bundle.close()
