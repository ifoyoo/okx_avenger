# CLI App Command Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `cli.py` as the only real entry file while moving parser construction, command registration, runtime helpers, and command handlers into a dedicated `cli_app/` package.

**Architecture:** `cli.py` becomes a thin facade over `cli_app.main()` and `cli_app.build_parser()`. `cli_app/parser.py` and `cli_app/registry.py` own parser construction, `cli_app/context.py` and `cli_app/helpers.py` own shared runtime/helper logic, and `cli_app/commands/*.py` own command handlers grouped by responsibility.

**Tech Stack:** Python, `argparse`, existing OKX client/runtime code, `pytest`

---

### Task 1: Lock Entry And Helper Contracts Before Refactor

**Files:**
- Modify: `tests/test_cli_entrypoints.py`
- Modify: `tests/test_cli_parser.py`
- Modify: `tests/test_cli_runtime_heartbeat.py`
- Modify: `tests/test_cli_backtest_tune_utils.py`

- [ ] **Step 1: Write the failing tests for the thin-entry contract**

```python
from __future__ import annotations

import argparse
from pathlib import Path

import cli


def test_cli_main_dispatches_parser_selected_handler(monkeypatch) -> None:
    parser = argparse.ArgumentParser()

    def fake_status(_args) -> int:
        return 17

    parser.set_defaults(func=fake_status)

    monkeypatch.setattr(cli, "build_parser", lambda: parser)

    assert cli.main([]) == 17


def test_cli_build_parser_exposes_runtime_commands() -> None:
    parser = cli.build_parser()
    help_text = parser.format_help()

    assert "once" in help_text
    assert "run" in help_text
    assert "status" in help_text
    assert "config-check" in help_text
```

- [ ] **Step 2: Write the failing tests for helper-module imports**

```python
from __future__ import annotations

from pathlib import Path

from cli_app.helpers import _read_runtime_heartbeat, _write_runtime_heartbeat


def test_runtime_heartbeat_roundtrip(tmp_path) -> None:
    path = Path(tmp_path) / "runtime_heartbeat.json"
    _write_runtime_heartbeat(path=path, status="running", cycle=3, exit_code=0, detail="")
    payload = _read_runtime_heartbeat(path)
    assert payload is not None
    assert payload["status"] == "running"
```

```python
from __future__ import annotations

import pandas as pd

from cli_app.helpers import _market_regime_bucket, _plugin_score, _scores_to_weights


def test_scores_to_weights_monotonic() -> None:
    weights = _scores_to_weights({"a": 0.1, "b": 0.2, "c": 0.3})
    assert weights["a"] < weights["b"] < weights["c"]
```

- [ ] **Step 3: Run tests to verify they fail for the right reason**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q \
  tests/test_cli_entrypoints.py \
  tests/test_cli_runtime_heartbeat.py \
  tests/test_cli_backtest_tune_utils.py
```

Expected:
- `test_cli_main_dispatches_parser_selected_handler` fails because current `cli.main()` still builds the real parser instead of the monkeypatched stub.
- helper import tests fail because `cli_app.helpers` does not exist yet.

- [ ] **Step 4: Update tests to the new contract and rerun until the failures are purely missing-implementation failures**

```python
from cli import build_parser, main
from cli_app.helpers import _read_runtime_heartbeat, _write_runtime_heartbeat
from cli_app.helpers import _market_regime_bucket, _plugin_score, _scores_to_weights
```

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q \
  tests/test_cli_entrypoints.py \
  tests/test_cli_parser.py \
  tests/test_cli_runtime_heartbeat.py \
  tests/test_cli_backtest_tune_utils.py
```

Expected:
- Tests still fail, but now only because `cli_app` package and thin-entry behavior have not been implemented yet.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py
git commit -m "test: lock cli app refactor contracts"
```

### Task 2: Create The CLI Package Skeleton And Move Parser Construction

**Files:**
- Create: `cli_app/__init__.py`
- Create: `cli_app/parser.py`
- Create: `cli_app/registry.py`
- Create: `cli_app/commands/__init__.py`
- Modify: `cli.py`

- [ ] **Step 1: Create the new package entrypoints**

```python
# cli_app/__init__.py
from .parser import build_parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))
```

```python
# cli_app/commands/__init__.py
"""CLI command modules."""
```

- [ ] **Step 2: Create the explicit registry and parser shell**

```python
# cli_app/registry.py
from .commands.backtest import register_backtest_commands
from .commands.config import register_config_commands
from .commands.runtime import register_runtime_commands
from .commands.strategies import register_strategy_commands

REGISTER_COMMANDS = (
    register_runtime_commands,
    register_config_commands,
    register_backtest_commands,
    register_strategy_commands,
)
```

```python
# cli_app/parser.py
import argparse

from .registry import REGISTER_COMMANDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="okx", description="OKX 自动交易 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for register in REGISTER_COMMANDS:
        register(sub)
    return parser
```

- [ ] **Step 3: Add temporary command stubs so parser construction works before full migration**

```python
# cli_app/commands/config.py
import argparse


def cmd_config_check(_args: argparse.Namespace) -> int:
    raise NotImplementedError


def register_config_commands(subparsers) -> None:
    parser = subparsers.add_parser("config-check", help="检查配置")
    parser.add_argument("--api-check", action="store_true", help="执行 API 联通性检查")
    parser.set_defaults(func=cmd_config_check)
```

Use the same pattern for:
- `cli_app/commands/runtime.py`
- `cli_app/commands/strategies.py`
- `cli_app/commands/backtest.py`

The stubs only need to register current command names and arguments. Handler bodies can temporarily raise `NotImplementedError`.

- [ ] **Step 4: Make `cli.py` a thin facade over the package**

```python
"""简洁 CLI 入口：支持 run / once / status / config-check / strategies / backtest."""

from cli_app import build_parser, main


if __name__ == "__main__":
    raise SystemExit(main())
```

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py tests/test_cli_parser.py
```

Expected:
- parser/entry tests pass
- helper tests still fail because helper extraction is not finished

- [ ] **Step 5: Commit the parser migration**

```bash
git add cli.py cli_app/__init__.py cli_app/parser.py cli_app/registry.py cli_app/commands/__init__.py cli_app/commands/config.py cli_app/commands/runtime.py cli_app/commands/strategies.py cli_app/commands/backtest.py tests/test_cli_entrypoints.py tests/test_cli_parser.py
git commit -m "refactor: move cli parser into cli_app package"
```

### Task 3: Extract Shared Helpers And Move Status / Config Commands

**Files:**
- Create: `cli_app/context.py`
- Create: `cli_app/helpers.py`
- Modify: `cli_app/commands/runtime.py`
- Modify: `cli_app/commands/config.py`
- Modify: `tests/test_cli_runtime_heartbeat.py`
- Modify: `tests/test_cli_backtest_tune_utils.py`

- [ ] **Step 1: Move runtime bundle and logger setup into `cli_app/context.py`**

```python
from dataclasses import dataclass

from config.settings import AppSettings, get_settings
from core.analysis import MarketAnalyzer
from core.client import OKXClient
from core.data.performance import PerformanceTracker
from core.data.watchlist_loader import WatchlistManager
from core.engine.trading import TradingEngine
from core.strategy.core import Strategy


@dataclass
class RuntimeBundle:
    settings: AppSettings
    okx: OKXClient
    engine: TradingEngine
    watchlist_manager: WatchlistManager
    perf_tracker: PerformanceTracker
```

- [ ] **Step 2: Move heartbeat, ratio, backtest-score, and regime helpers into `cli_app/helpers.py`**

```python
def _write_runtime_heartbeat(*, path: Path, status: str, cycle: int = 0, exit_code: int = 0, detail: str = "") -> None:
    ...


def _read_runtime_heartbeat(path: Path) -> Optional[Dict[str, Any]]:
    ...


def _plugin_score(summary: Dict[str, Any], initial_equity: float) -> float:
    ...


def _market_regime_bucket(features: pd.DataFrame) -> str:
    ...


def _scores_to_weights(scores: Dict[str, float]) -> Dict[str, float]:
    ...
```

- [ ] **Step 3: Implement `status` and `config-check` in their command modules using the extracted helpers**

```python
def register_runtime_commands(subparsers) -> None:
    p_once = subparsers.add_parser("once", help="执行一轮扫描")
    ...
    p_status = subparsers.add_parser("status", help="查看账户、持仓、watchlist 状态")
    p_status.set_defaults(func=cmd_status)
```

```python
def register_config_commands(subparsers) -> None:
    parser = subparsers.add_parser("config-check", help="检查配置")
    parser.add_argument("--api-check", action="store_true", help="执行 API 联通性检查")
    parser.set_defaults(func=cmd_config_check)
```

- [ ] **Step 4: Run the helper and lightweight-command tests**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q \
  tests/test_cli_entrypoints.py \
  tests/test_cli_parser.py \
  tests/test_cli_runtime_heartbeat.py \
  tests/test_cli_backtest_tune_utils.py
```

Expected:
- All tests above pass

- [ ] **Step 5: Commit the shared helper extraction**

```bash
git add cli_app/context.py cli_app/helpers.py cli_app/commands/runtime.py cli_app/commands/config.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py
git commit -m "refactor: extract cli runtime helpers"
```

### Task 4: Move Runtime Commands Into `cli_app/commands/runtime.py`

**Files:**
- Modify: `cli_app/commands/runtime.py`
- Modify: `cli_app/context.py`
- Modify: `cli_app/helpers.py`

- [ ] **Step 1: Write or preserve the runtime command registration helpers**

```python
def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--inst", help="指定单个交易对，例如 BTC-USDT-SWAP")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="K线周期，默认 5m")
    parser.add_argument("--higher-timeframes", default="1H", help="高阶周期，逗号分隔，例如 1H,4H")
    parser.add_argument("--max-position", type=float, default=0.0, help="单标的最大下单量（覆盖 watchlist）")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="K线数量，默认 150")
    parser.add_argument("--dry-run", action="store_true", help="仿真模式，不实际下单")
```

- [ ] **Step 2: Move `cmd_once`, `cmd_run`, `cmd_status`, and runtime-only helpers**

```python
def cmd_once(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    heartbeat_path = Path(bundle.settings.runtime.runtime_heartbeat_path)
    ...
```

```python
def cmd_run(args: argparse.Namespace) -> int:
    bundle = build_runtime()
    ...
```

Also move:
- `_safe_account_snapshot`
- `_resolve_entries`
- `_run_cycle`
- `_log_strategy_snapshot`
- `_parse_timeframes`
- `_fmt_action`
- `_fmt_plan`
- `_human_ratio`

- [ ] **Step 3: Remove the moved runtime logic from `cli.py` and keep only facade imports**

```python
from cli_app import build_parser, main
```

No runtime implementation should remain in `cli.py`.

- [ ] **Step 4: Run the focused runtime verification**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py
/Users/t/Desktop/Python/okx/.venv/bin/python cli.py --help
./okx --help
```

Expected:
- all focused tests pass
- both help commands exit `0`

- [ ] **Step 5: Commit the runtime command migration**

```bash
git add cli.py cli_app/context.py cli_app/helpers.py cli_app/commands/runtime.py
git commit -m "refactor: move cli runtime commands"
```

### Task 5: Move Strategies And Backtest Commands, Then Thin Final Entry

**Files:**
- Modify: `cli_app/commands/strategies.py`
- Modify: `cli_app/commands/backtest.py`
- Modify: `cli_app/helpers.py`
- Modify: `tests/test_cli_parser.py`
- Modify: `tests/test_cli_backtest_tune_utils.py`
- Modify: `tests/test_cli_entrypoints.py`

- [ ] **Step 1: Move the strategy-management implementation into `cli_app/commands/strategies.py`**

```python
def cmd_strategies(args: argparse.Namespace) -> int:
    _refresh_settings_cache()
    settings = get_settings()
    names = _strategy_names_from_settings(settings)
    ...
```

Also move helper functions used only by strategies:
- `_refresh_settings_cache`
- `_strategy_names_from_settings`
- `_normalize_names`
- `_ordered_join`
- `_current_enabled_set`
- `_current_weight_map`
- `_save_env_key`
- `_save_enabled_config`
- `_save_weight_config`
- `_print_strategies`

- [ ] **Step 2: Move backtest/report/tune implementation into `cli_app/commands/backtest.py`**

```python
def cmd_backtest_run(args: argparse.Namespace) -> int:
    ...


def cmd_backtest_report(args: argparse.Namespace) -> int:
    ...


def cmd_backtest_tune(args: argparse.Namespace) -> int:
    ...
```

Also move helper functions used only by backtest:
- `_serialize_backtest_record`
- `_save_backtest_records`
- `_load_backtest_records`
- `_print_backtest_summary`
- `_build_features_for_backtest`
- `_run_single_backtest`
- `_safe_float`

- [ ] **Step 3: Ensure `cli.py` remains a thin facade and `cli_app/__init__.py` owns the public API**

```python
# cli.py
from cli_app import build_parser, main


if __name__ == "__main__":
    raise SystemExit(main())
```

No command handlers or helper functions should remain in `cli.py`.

- [ ] **Step 4: Run the full focused verification suite**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q \
  tests/test_cli_entrypoints.py \
  tests/test_cli_parser.py \
  tests/test_cli_runtime_heartbeat.py \
  tests/test_cli_backtest_tune_utils.py
/Users/t/Desktop/Python/okx/.venv/bin/python cli.py --help
./okx --help
git diff --check -- cli.py cli_app tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py
```

Expected:
- all focused tests pass
- both help commands exit `0`
- `git diff --check` is clean

- [ ] **Step 5: Commit the final command-package migration**

```bash
git add cli.py cli_app tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py
git commit -m "refactor: split cli into command package"
```
