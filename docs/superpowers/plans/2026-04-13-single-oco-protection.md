# Single OCO Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-fill attached TP/SL orders with a single exchange-side OCO per live position.

**Architecture:** Add an exchange protection reconciler that reads live positions plus live OCO algo orders, then creates, amends, or cancels one OCO per position. Runtime will disable `attachAlgoOrds` in live mode when the reconciler is active and feed it per-instrument TP/SL percentages from watchlist/default config.

**Tech Stack:** Python, OKX SDK, pytest

---

### Task 1: Reconciler tests

**Files:**
- Create: `tests/test_protection_order_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_enforce_places_single_oco_for_live_long_position():
    ...

def test_enforce_cancels_duplicate_oco_orders_before_recreating():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_protection_order_manager.py -q`
Expected: FAIL because the reconciler does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class ProtectionOrderManager:
    def enforce(self) -> None:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_protection_order_manager.py -q`
Expected: PASS

### Task 2: OKX client support

**Files:**
- Modify: `core/client/rest.py`
- Modify: `core/engine/__init__.py`

- [ ] **Step 1: Add failing integration tests or adapt existing runtime tests**

```python
assert call["exchange_protection_enabled"] is False
```

- [ ] **Step 2: Run affected tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_cli_runtime_cycle.py tests/test_cli_runtime_workflows.py -q`
Expected: FAIL until client and manager APIs are wired.

- [ ] **Step 3: Add client helpers**

```python
def list_algo_orders(...): ...
def place_algo_order(...): ...
def amend_algo_order(...): ...
```

- [ ] **Step 4: Re-run affected tests**

Run: `./.venv/bin/python -m pytest tests/test_cli_runtime_cycle.py tests/test_cli_runtime_workflows.py -q`
Expected: PASS

### Task 3: Runtime wiring

**Files:**
- Modify: `cli_app/context.py`
- Modify: `cli_app/runtime_execution.py`
- Modify: `cli_app/runtime_workflows.py`
- Modify: `core/engine/trading.py`

- [ ] **Step 1: Keep failing runtime tests in place**

```python
assert monitor.thresholds == [...]
```

- [ ] **Step 2: Wire runtime to use the reconciler**

```python
exchange_protection_enabled=protection_monitor is None or bool(args.dry_run)
```

- [ ] **Step 3: Run targeted tests**

Run: `./.venv/bin/python -m pytest tests/test_trading_pipeline.py tests/test_cli_runtime_cycle.py tests/test_cli_runtime_workflows.py tests/test_protection_order_manager.py -q`
Expected: PASS

### Task 4: Full verification

**Files:**
- Modify: `tests/test_llm_brain.py`
- Modify: `tests/test_execution_clordid.py`
- Modify: `tests/test_trading_pipeline.py`

- [ ] **Step 1: Run full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS with zero failures.
