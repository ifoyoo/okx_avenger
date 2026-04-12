# LLM Structured Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed structured market and intel context into `LLMBrain` so the prompt consumes the outputs of the earlier refactors directly.

**Architecture:** Keep the existing `analyze()` API compatible, but add optional structured context arguments and compact them into a bounded JSON block in the prompt. Trading passes these compact structures from `analysis_result` and `market_intel`.

**Tech Stack:** Python, pytest

---

### Task 1: Add failing prompt-context tests

**Files:**
- Modify: `tests/test_llm_brain.py`

### Task 2: Implement structured context plumbing

**Files:**
- Modify: `core/analysis/llm_brain.py`
- Modify: `core/engine/trading.py`

### Task 3: Verify full suite and update handoff docs
