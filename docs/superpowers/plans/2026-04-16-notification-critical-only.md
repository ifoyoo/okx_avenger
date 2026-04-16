# Notification Critical-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove success-order Telegram pushes so runtime notifications only carry actionable alerts.

**Architecture:** Keep the existing `NotificationCenter` and runtime event model, but stop publishing `order_submitted` and collapse all configured notification levels into the same critical-only filter. Update docs so config examples and decision notes match the new behavior.

**Tech Stack:** Python, dataclasses, pytest, Markdown docs

---

### Task 1: Lock the critical-only contract with tests

**Files:**
- Modify: `tests/test_notifications.py`
- Modify: `tests/test_cli_runtime_cycle.py`
- Modify: `tests/test_settings_validation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_notification_center_treats_all_levels_as_critical_only() -> None:
    transport = _Transport()
    center = NotificationCenter(transport=transport, level="orders", cooldown_seconds=60.0)

    center.publish(NotificationEvent(kind="order_submitted", inst_id="BTC-USDT-SWAP"))
    center.publish(NotificationEvent(kind="order_failed", inst_id="BTC-USDT-SWAP", detail="rejected"))

    assert [item[0] for item in transport.messages] == [
        "[ORDER FAILED]\nBTC-USDT-SWAP\nrejected",
    ]


def test_run_runtime_cycle_does_not_send_success_notification() -> None:
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_notifications.py tests/test_cli_runtime_cycle.py tests/test_settings_validation.py`
Expected: FAIL because success notifications are still emitted and `orders` still allows `order_submitted`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/utils/notifications.py
def normalize_level(level: object) -> str:
    normalized = str(level or "critical").strip().lower()
    if normalized not in {"critical", "orders", "all"}:
        return "critical"
    return "critical"
```

```python
# cli_app/runtime_execution.py
if success:
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/test_notifications.py tests/test_cli_runtime_cycle.py tests/test_settings_validation.py`
Expected: PASS

### Task 2: Align docs with the new alert-only behavior

**Files:**
- Modify: `README.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/SESSION_STATE.md`
- Modify: `docs/NEXT_STEP.md`

- [ ] **Step 1: Update docs**

```markdown
- change `NOTIFY_LEVEL=orders` examples to `NOTIFY_LEVEL=critical`
- describe Telegram as critical-only alerting
- remove mentions of success-order notifications
```

- [ ] **Step 2: Run focused verification**

Run: `.venv/bin/python -m pytest -q tests/test_notifications.py tests/test_cli_runtime_cycle.py tests/test_settings_validation.py`
Expected: PASS

Run: `git diff --check`
Expected: clean
