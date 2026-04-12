# Notification Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the notification module with the real runtime flow and make Telegram notifications actually work from `run_once/run`.

**Architecture:** A `NotificationCenter` will sit above a Telegram transport and below the runtime workflow. Runtime execution publishes concrete events such as blocked trades, order failures, and successful orders; the center applies level filtering and cooldown before dispatching messages.

**Tech Stack:** Python, dataclasses, requests, pytest

---

### Task 1: Lock the notification contract with tests

**Files:**
- Create: `tests/test_notifications.py`
- Modify: `tests/test_cli_runtime_cycle.py`
- Modify: `tests/test_cli_runtime_workflows.py`
- Modify: `tests/test_settings_validation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_notification_center_filters_events_by_level():
    ...


def test_runtime_cycle_sends_blocked_or_order_notifications():
    ...


def test_runtime_workflow_sends_runtime_error_notification():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_notifications.py tests/test_cli_runtime_cycle.py tests/test_cli_runtime_workflows.py tests/test_settings_validation.py`
Expected: FAIL because the runtime path does not build or use a notification center yet.

- [ ] **Step 3: Write minimal implementation**

```python
# core/utils/notifications.py
@dataclass
class NotificationEvent:
    ...

class NotificationCenter:
    ...
```

```python
# cli_app/context.py
notifier = build_notification_center(settings.notification)
```

```python
# cli_app/runtime_execution.py
_notify_runtime_result(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/test_notifications.py tests/test_cli_runtime_cycle.py tests/test_cli_runtime_workflows.py tests/test_settings_validation.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_notifications.py tests/test_cli_runtime_cycle.py tests/test_cli_runtime_workflows.py tests/test_settings_validation.py core/utils/notifications.py core/utils/__init__.py cli_app/context.py cli_app/runtime_execution.py cli_app/runtime_workflows.py config/settings.py
git commit -m "refactor: wire runtime notifications"
```

### Task 2: Sync docs and run full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/SESSION_STATE.md`
- Modify: `docs/NEXT_STEP.md`

- [ ] **Step 1: Update docs**

```markdown
- describe runtime notification center
- document concrete `NOTIFY_LEVEL` semantics
- remove claims that imply notifications work outside runtime flow
```

- [ ] **Step 2: Run full verification**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 3: Run config and diff checks**

Run: `./okx config-check`
Expected: PASS

Run: `git diff --check`
Expected: clean

- [ ] **Step 4: Commit**

```bash
git add README.md docs/DECISIONS.md docs/SESSION_STATE.md docs/NEXT_STEP.md
git commit -m "docs: describe runtime notification flow"
```
