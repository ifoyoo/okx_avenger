# CLI Entry Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate runtime startup under `cli.py` by deleting the legacy `main.py` entrypoint, keeping `okx` as a thin launcher to `cli.py`, and syncing tests/internal handoff docs to the single-entry architecture.

**Architecture:** `cli.py` already owns parser construction, runtime bundle assembly, command dispatch, and heartbeat persistence, so the implementation keeps that path intact and removes the duplicate `main.py` orchestration path entirely. Regression coverage is centered on entry ownership: `cli.main(...)` dispatch, `okx` launcher target, and repository-level absence of `main.py`, followed by internal docs updates that describe the new N2 state and restore `NEXT_STEP` to cli-only observation work.

**Tech Stack:** Python 3, argparse, pytest, pathlib, shell launcher script, Markdown docs

---

## File Structure

- `cli.py:955-1062`
  - Keep as the only real Python entrypoint via `build_parser()` and `main(argv)`.
  - No functional rewrite is expected unless the new dispatch test exposes an issue.
- `main.py:1-1022`
  - Delete entirely.
  - This removes the Rich startup UI, confirmation prompt, duplicate scheduler, duplicate runtime wiring, and duplicate notifier/display path in one step.
- `okx:1-10`
  - Keep unchanged as the shell launcher that executes `cli.py`.
  - Verify in tests that it still points to `cli.py` and never references `main.py`.
- `tests/test_cli_entrypoints.py`
  - Create a focused regression file for single-entry ownership.
  - Hold the `cli.main(["status"])` dispatch test, the `okx` launcher target test, and the `main.py` removal test.
- `docs/NODES.md:43-55`
  - Update N2 to describe `cli.py` + `okx` only.
  - Remove the “Rich 面板入口” wording and record the old-entry deletion as completed work.
- `docs/SESSION_STATE.md`
  - Add a new latest-completed entry for the N2 follow-up.
  - Update top-level metadata to show the project is back in cli-only runtime mode.
- `docs/DECISIONS.md`
  - Add a new top decision recording the hard cutover to `cli.py` as the only entrypoint.
- `docs/NEXT_STEP.md`
  - Replace the current next-step target with “return to cli-only observation/tuning,” explicitly saying not to restore `main.py` or startup UI.
- `README.md`
  - Leave unchanged in this plan.

### Task 1: Lock Single-Entry Ownership With Tests And Remove `main.py`

**Files:**
- Delete: `main.py`
- Create: `tests/test_cli_entrypoints.py`
- Test: `tests/test_cli_entrypoints.py`
- Test: `tests/test_cli_parser.py`
- Test: `tests/test_cli_runtime_heartbeat.py`
- Test: `tests/test_cli_backtest_tune_utils.py`
- Verify only: `okx`

- [ ] **Step 1: Write the failing regression tests**

Create `tests/test_cli_entrypoints.py` with this exact content:

```python
"""CLI 单入口约束测试。"""

from __future__ import annotations

from pathlib import Path

import cli


def test_cli_main_dispatches_selected_handler(monkeypatch) -> None:
    calls: list[str] = []

    def fake_status(args) -> int:
        calls.append(args.command)
        return 17

    monkeypatch.setattr(cli, "cmd_status", fake_status)

    assert cli.main(["status"]) == 17
    assert calls == ["status"]


def test_okx_launcher_targets_cli_py() -> None:
    content = Path("okx").read_text(encoding="utf-8")

    assert '"${SCRIPT_DIR}/cli.py"' in content
    assert "main.py" not in content


def test_main_py_is_removed() -> None:
    assert not Path("main.py").exists()
```

- [ ] **Step 2: Run the new test file and verify it fails for the right reason**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py
```

Expected:

```text
..F
=================================== FAILURES ===================================
___________________________ test_main_py_is_removed ____________________________
E       AssertionError: assert not True
```

- [ ] **Step 3: Remove the legacy Python entrypoint instead of forwarding it**

Delete `main.py` entirely. The change should be a pure file removal, with no replacement shim and no forwarding wrapper:

```diff
*** Delete File: main.py
```

After deletion, leave `cli.py` and `okx` unchanged unless the test from Step 1 exposed an actual dispatch bug. The intended execution tree is:

```text
./okx ... -> cli.py -> cli.main(argv)
python cli.py ... -> cli.main(argv)
```

- [ ] **Step 4: Run the focused regression suite and make sure the single-entry path passes**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py
```

Expected:

```text
16 passed
```

- [ ] **Step 5: Verify the remaining safe launch surfaces without touching the network**

Run:

```bash
.venv/bin/python cli.py --help
./okx --help
```

Expected:

```text
Both commands exit with code 0.
Both outputs contain "usage: okx".
Both outputs list the subcommands "once", "run", "status", "config-check", "strategies", and "backtest".
```

- [ ] **Step 6: Commit the entrypoint consolidation change**

Run:

```bash
git add tests/test_cli_entrypoints.py
git add -u main.py
git commit -m "refactor: remove legacy main entrypoint"
```

### Task 2: Sync Internal Architecture And Handoff Docs To The CLI-Only State

**Files:**
- Modify: `docs/NODES.md:43-55`
- Modify: `docs/SESSION_STATE.md:5-30`
- Modify: `docs/DECISIONS.md:5-21`
- Modify: `docs/NEXT_STEP.md:5-27`

- [ ] **Step 1: Update N2 in `docs/NODES.md` so it no longer advertises `main.py`**

Replace the current N2 section with this exact content:

```markdown
## N2 入口与调度层
- **文件**：`cli.py`、`okx`
- **输入**：CLI 参数 + `AppSettings`
- **输出**：单轮执行请求/循环调度
- **当前实现**
  - `okx` 仅作为 shell 包装，统一转调 `cli.py`
  - `cli.py` 提供 `once/run/status/config-check/strategies/backtest`
- **风险点**
  - `cli.py` 同时承担命令装配与运行编排，文件体积仍偏大
  - `run` 常驻调度缺“健康探针/自愈重启”
- **优化待办**
  - [x] 收口为 `cli.py` 单入口并删除 `main.py` 重复调度
  - [x] 增加运行健康状态文件（heartbeat）
```

- [ ] **Step 2: Update the handoff docs to record the hard cutover and restore the next target**

Add a new top entry to `docs/DECISIONS.md`:

```markdown
### 2026-04-10 - D0011 - N2 收口为 `cli.py` 单入口并删除 `main.py`
- 背景：`cli.py` 已具备完整 runtime/heartbeat/命令分发能力，但仓库仍保留 `main.py` 的 Rich 启动界面、确认交互和独立调度，导致入口重复。
- 决策：
  - 删除 `main.py` 旧入口，不保留转发 shim。
  - 保留 `okx -> cli.py` 作为唯一启动链路。
  - 删除 Rich 启动界面、`y` 确认、独立 `schedule` 调度和重复展示逻辑。
  - 本轮只同步内部架构与交接文档，不改 `README.md`。
- 原因：直接消除重复入口比保留兼容壳更清晰，能避免运行行为漂移，并符合“与目标方向冲突的旧实现不保留兜底分支”的执行约束。
- 影响：项目启动入口收敛为 `./okx ...` 或 `python cli.py ...`；`python main.py` 不再受支持；N2 文档和交接状态改为 cli-only 语义。
- 回滚方案：如后续必须兼容旧习惯，可在单独变更中新增极薄 `main.py` 提示或转发层，但不恢复旧 Rich/schedule 实现。
```

Insert a new latest-completed item near the top of `docs/SESSION_STATE.md`, and update the metadata block so it reflects the new state:

```markdown
## 元信息
- 最后更新时间：2026-04-10
- 当前主线：按 `docs/NODES.md` 推进
- 当前批次：N2 入口收口 / CLI 单入口
- 当前节点：已删除 `main.py` 旧入口，当前回到 cli-only 运行与观测准备
```

```markdown
- 时间：2026-04-10
- 节点：N2 follow-up / CLI 单入口
- 目标：删除重复入口，去掉启动界面与确认交互，把 Python 侧运行入口收口到 `cli.py`
- 结果：完成。`main.py` 已删除，Rich 启动画面、`y` 确认、独立 `schedule` 调度与重复展示逻辑一并移除；`okx` 继续只作为 shell 包装转到 `cli.py`；新增 `tests/test_cli_entrypoints.py` 锁定 `cli.main(...)` 分发、`okx -> cli.py` 目标以及 `main.py` 缺失约束。
- 变更文件：
  - `main.py`
  - `tests/test_cli_entrypoints.py`
  - `docs/NODES.md`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py` -> `16 passed`
  - `.venv/bin/python cli.py --help` -> `exit 0`
  - `./okx --help` -> `exit 0`
- 产物/日志：
  - 启动入口收口为 `./okx ...` / `python cli.py ...`
  - `main.py` 不再作为受支持入口
```

Replace the target section in `docs/NEXT_STEP.md` with this exact content:

```markdown
## 下一步唯一目标
- N2 入口收口已完成。下一步回到“cli-only 实盘观测期”：使用 `./okx run` 或 `./okx once --dry-run` 连续运行，并基于 heartbeat/决策日志做参数微调，不恢复 `main.py` 或启动 UI。

## 执行范围（预期会改）
- `logs/`、`data/config_snapshot.json`、`data/runtime_heartbeat.json`（运行观测）
- 必要时仅调整 `.env` 参数与少量阈值配置
- `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`

## 执行约束
- 重构优先：遇到与目标方向冲突的旧实现，不新增兼容分支或兜底逻辑；调用方与测试同步到新契约。

## 完成判据（验收）
1. 连续运行期间 heartbeat 持续更新且无异常中断。
2. 决策日志能观测关键事件（risk/intel/arb/execution）。
3. 参数调整后全量测试保持通过。
4. 持续使用 `cli.py` / `okx` 单入口，不恢复 `main.py` 启动路径。
5. 三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
```

- [ ] **Step 3: Run the final non-network verification after the docs are synced**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py
.venv/bin/python cli.py --help
./okx --help
```

Expected:

```text
The pytest command reports 16 passed.
The two help commands exit with code 0 and still print the same command list.
```

- [ ] **Step 4: Commit the documentation and handoff sync**

Run:

```bash
git add docs/NODES.md docs/SESSION_STATE.md docs/DECISIONS.md docs/NEXT_STEP.md
git commit -m "docs: sync cli-only entrypoint state"
```
