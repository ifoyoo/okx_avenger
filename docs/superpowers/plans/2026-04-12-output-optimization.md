# Output Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 CLI、runtime、通知和 backtest 的输出契约，让项目输出更适合人类扫读和交付后观测。

**Architecture:** 保持现有纯文本输出路线，不引入 Rich/TUI。以 reporting/helpers/template 为边界做“表达层重构”，通过测试锁定新的输出契约，避免误改交易逻辑。

**Tech Stack:** Python, pytest, loguru, existing CLI reporting modules

---

### Task 1: Config And Status Output Contract

**Files:**
- Modify: `cli_app/config_reporting.py`
- Modify: `cli_app/runtime_reporting.py`
- Modify: `cli_app/runtime_status_helpers.py`
- Test: `tests/test_cli_config_reporting.py`
- Test: `tests/test_cli_runtime_reporting.py`
- Test: `tests/test_cli_status_formatting.py`

- [ ] 写 failing tests，锁定新的 `config-check` 分组摘要输出
- [ ] 运行相关测试，确认因旧格式失败
- [ ] 实现新的 config summary 输出
- [ ] 写 failing tests，锁定新的 runtime status 页面结构与 section 文案
- [ ] 运行相关测试，确认因旧格式失败
- [ ] 实现新的 status 输出与 helper 文案
- [ ] 回跑本任务相关测试确认通过

### Task 2: Runtime Cycle Log Contract

**Files:**
- Modify: `cli_app/runtime_execution.py`
- Test: `tests/test_cli_runtime_cycle.py`

- [ ] 写 failing tests，锁定新的 cycle summary 文案和 per-inst 输出重点
- [ ] 运行相关测试，确认因旧格式失败
- [ ] 实现新的 runtime cycle 日志表达
- [ ] 回跑相关测试确认通过

### Task 3: Notification Template Refactor

**Files:**
- Modify: `core/utils/notifications.py`
- Modify: `cli_app/runtime_execution.py`
- Test: `tests/test_notifications.py`
- Test: `tests/test_cli_runtime_cycle.py`

- [ ] 写 failing tests，锁定通知模板渲染结果
- [ ] 运行相关测试，确认因旧模板失败
- [ ] 实现事件到短通知模板的渲染逻辑
- [ ] 调整 runtime 侧事件构造，避免继续塞原始长 message
- [ ] 回跑相关测试确认通过

### Task 4: Backtest Report Summary Contract

**Files:**
- Modify: `cli_app/backtest_reporting.py`
- Modify: `cli_app/backtest_helpers.py`
- Test: `tests/test_cli_backtest_reporting.py`
- Test: `tests/test_cli_backtest_workflows.py`

- [ ] 写 failing tests，锁定新的 backtest summary / trade / tune 输出结构
- [ ] 运行相关测试，确认因旧格式失败
- [ ] 实现新的 backtest 报告输出
- [ ] 回跑相关测试确认通过

### Task 5: Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/SESSION_STATE.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/NEXT_STEP.md`

- [ ] 更新 README 中与输出体验相关的说明（若有必要）
- [ ] 同步三份交接文档
- [ ] 运行 targeted pytest
- [ ] 运行 full pytest
- [ ] 手动执行 `./okx config-check` 和 `./okx status` 做 smoke check
