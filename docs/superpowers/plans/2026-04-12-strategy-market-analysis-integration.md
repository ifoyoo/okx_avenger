# Strategy Market Analysis Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect `MarketAnalysis v2` into strategy generation so deterministic structured market analysis can influence fusion without breaking the current LLM JSON path.

**Architecture:** Keep `analysis_text` compatibility, but add `market_analysis` as an optional structured input. `AnalysisInterpreter.from_market_analysis()` turns structured market output into `AnalysisView`, and `Strategy.generate_signal()` chooses it when the incoming analysis text is not a stronger structured LLM decision.

**Tech Stack:** Python, dataclasses, pytest

---

### Task 1: Add Failing Tests For Structured Analysis Integration

**Files:**
- Modify: `tests/test_strategy_core.py`
- Modify: `tests/test_trading_pipeline.py`

- [ ] **Step 1: Add failing tests for `from_market_analysis()`**
- [ ] **Step 2: Add failing tests for `Strategy.generate_signal(..., market_analysis=...)`**
- [ ] **Step 3: Run focused tests and confirm failures**

### Task 2: Implement Interpreter And Strategy Wiring

**Files:**
- Modify: `core/strategy/fusion.py`
- Modify: `core/strategy/core.py`
- Modify: `core/engine/trading.py`

- [ ] **Step 1: Add `AnalysisInterpreter.from_market_analysis()`**
- [ ] **Step 2: Extend `Strategy.generate_signal()` with optional `market_analysis`**
- [ ] **Step 3: Pass `analysis_bundle.analysis_result` from trading pipeline**
- [ ] **Step 4: Run focused tests**

### Task 3: Full Verification And Handoff

**Files:**
- Modify: `docs/SESSION_STATE.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/NEXT_STEP.md`

- [ ] **Step 1: Run full test suite**
- [ ] **Step 2: Update handoff docs to next stage**
