# TP/SL Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify take-profit / stop-loss semantics so strategy, execution, and backtest use the same protection rules.

**Architecture:** `TradeSignal` carries normalized protection rules, `core/protection.py` resolves them into exchange/backtest targets using entry price plus ATR, and backtest exits positions with the same resolved levels used by execution. Runtime threshold aliases are normalized to the same rule vocabulary.

**Tech Stack:** Python, dataclasses, pytest, pandas

---

### Task 1: Lock the new protection contract with tests

**Files:**
- Create: `tests/test_protection_rules.py`
- Modify: `tests/test_backtest_simple.py`
- Modify: `tests/test_execution_clordid.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_resolve_trade_protection_supports_percent_alias_and_rr_take_profit():
    ...


def test_backtest_exits_with_take_profit_or_stop_loss_from_trade_protection():
    ...


def test_execution_builds_attach_algo_orders_from_resolved_rules():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_protection_rules.py tests/test_backtest_simple.py tests/test_execution_clordid.py`
Expected: FAIL because the new resolver and backtest behavior do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# core/models/__init__.py
@dataclass
class ResolvedTradeProtection:
    take_profit: Optional[ProtectionTarget] = None
    stop_loss: Optional[ProtectionTarget] = None
```

```python
# core/protection.py
def resolve_trade_protection(...):
    ...
```

```python
# core/backtest/simple.py
def _resolve_position_protection(...):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/test_protection_rules.py tests/test_backtest_simple.py tests/test_execution_clordid.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_protection_rules.py tests/test_backtest_simple.py tests/test_execution_clordid.py core/models/__init__.py core/protection.py core/backtest/simple.py core/engine/execution.py core/strategy/core.py core/engine/trading.py
git commit -m "feat: unify take profit and stop loss resolution"
```

### Task 2: Update docs and regression coverage

**Files:**
- Modify: `README.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/SESSION_STATE.md`

- [ ] **Step 1: Write the failing doc-facing regression tests if needed**

```python
# No extra automated doc test required for this task.
```

- [ ] **Step 2: Run focused regression suite**

Run: `.venv/bin/python -m pytest -q tests/test_strategy_core.py tests/test_trading_pipeline.py tests/test_protection_monitor_thresholds.py`
Expected: PASS after implementation adjustments.

- [ ] **Step 3: Update documentation**

```markdown
- describe `rr` mode
- describe `ratio -> percent` normalization
- describe backtest now honoring the same protection rules
```

- [ ] **Step 4: Run final verification**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/DECISIONS.md docs/SESSION_STATE.md
git commit -m "docs: record tp sl redesign"
```
