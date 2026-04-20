# Backtest Parity And Position Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore higher-timeframe parity in CLI backtests and make strategy sizing respect configured per-market position limits.

**Architecture:** Extend the existing CLI backtest helper/aggregation path so it fetches and passes higher-timeframe feature maps into the backtest runner, then adjust the strategy sizing path so the final clamp is based on the already risk-adjusted `base` size and the higher-timeframe gate direction reaches the sizer.

**Tech Stack:** Python, pandas, pytest, Markdown docs

---

### Task 1: Lock higher-timeframe backtest parity with tests

**Files:**
- Modify: `tests/test_cli_backtest_execution.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_collect_backtest_records_passes_higher_timeframe_features_to_runner(monkeypatch) -> None:
    ...
    assert run_calls[0]["higher_timeframe_features"] == higher_features


def test_collect_tuning_snapshot_passes_higher_timeframe_features_to_runner(monkeypatch) -> None:
    ...
    assert run_calls[0]["higher_timeframe_features"] == higher_features
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_cli_backtest_execution.py`
Expected: FAIL because `_run_single_backtest()` is called without `higher_timeframe_features`.

- [ ] **Step 3: Write minimal implementation**

```python
# cli_app/backtest_helpers.py
def _build_higher_timeframe_features_for_backtest(...):
    return {tf: _build_features_for_backtest(okx, inst_id, tf, limit) for tf in higher_timeframes}


def _run_single_backtest(..., higher_timeframe_features=None):
    return run_backtest_from_features(..., higher_timeframe_features=higher_timeframe_features)
```

```python
# cli_app/backtest_execution.py
higher_timeframes = tuple(item.get("higher_timeframes") or DEFAULT_HIGHER_TIMEFRAMES)
higher_features = _build_higher_timeframe_features_for_backtest(...)
result = _run_backtest_entry(..., higher_timeframe_features=higher_features)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/test_cli_backtest_execution.py`
Expected: PASS

### Task 2: Lock sizing semantics with tests

**Files:**
- Modify: `tests/test_strategy_positioning.py`
- Modify: `tests/test_strategy_core.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_position_sizer_allows_context_cap_above_legacy_global_cap() -> None:
    size = sizer.size(...)
    assert size == pytest.approx(0.25, rel=1e-6)


def test_generate_signal_uses_gate_direction_for_position_sizing(monkeypatch) -> None:
    ...
    assert captured.get("trend_bias") == SignalAction.BUY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_strategy_positioning.py tests/test_strategy_core.py`
Expected: FAIL because the sizer still clamps to `0.05` and `Strategy.generate_signal()` still passes `HOLD`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/strategy/positioning.py
cap = base
if action == SignalAction.SELL:
    cap *= mult
```

```python
# core/strategy/core.py
if gate_decision.allow_long and not gate_decision.allow_short:
    trend_bias = SignalAction.BUY
elif gate_decision.allow_short and not gate_decision.allow_long:
    trend_bias = SignalAction.SELL
else:
    trend_bias = SignalAction.HOLD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/test_strategy_positioning.py tests/test_strategy_core.py`
Expected: PASS

### Task 3: End-to-end verification and release

**Files:**
- Modify: `cli_app/backtest_helpers.py`
- Modify: `cli_app/backtest_execution.py`
- Modify: `core/strategy/positioning.py`
- Modify: `core/strategy/core.py`

- [ ] **Step 1: Run focused regression suite**

Run: `.venv/bin/python -m pytest -q tests/test_cli_backtest_execution.py tests/test_backtest_simple.py tests/test_strategy_positioning.py tests/test_strategy_core.py`
Expected: PASS

- [ ] **Step 2: Run representative CLI backtest**

Run: `.venv/bin/python ./okx backtest run --limit 600 --warmup 120`
Expected: report includes non-zero trades for at least part of the configured basket instead of universal `0 trades`.

- [ ] **Step 3: Run diff hygiene**

Run: `git diff --check`
Expected: clean

- [ ] **Step 4: Commit and publish**

Run: `git add docs/superpowers/specs/2026-04-16-backtest-parity-and-position-sizing-design.md docs/superpowers/plans/2026-04-16-backtest-parity-and-position-sizing.md tests/test_cli_backtest_execution.py tests/test_strategy_positioning.py tests/test_strategy_core.py cli_app/backtest_helpers.py cli_app/backtest_execution.py core/strategy/positioning.py core/strategy/core.py`

Run: `git commit -m "fix: restore backtest gate parity and sizing caps"`

Run: `git push`
Expected: remote branch updated and ready for VPS sync
