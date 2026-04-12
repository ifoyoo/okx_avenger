# Intel Relevance Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unified relevance scoring to intel collection so all providers are filtered and aggregated using asset relevance, while preserving the existing `MarketIntelSnapshot` contract.

**Architecture:** Keep `NewsIntelCollector` as the public entry point, but add article-level relevance scoring and weighted aggregation inside `collect()`. Extend `NewsHeadline` and `MarketIntelSnapshot` with relevance metadata while preserving legacy fields.

**Tech Stack:** Python, dataclasses, requests, pytest

---

### Task 1: Lock The Relevance Contract With Failing Tests

**Files:**
- Modify: `tests/test_intel.py`

- [ ] **Step 1: Add failing tests for NewsAPI relevance filtering**

```python
def test_newsapi_articles_are_filtered_by_alias_relevance(monkeypatch) -> None:
    ...
    snapshot = collector.collect(
        "OL-USDT-SWAP",
        symbol_aliases=("Open Loot", "OpenLoot"),
    )

    assert snapshot is not None
    assert len(snapshot.headlines) == 1
    assert snapshot.headlines[0].title == "Open Loot expands creator ecosystem"
```

- [ ] **Step 2: Add failing tests for headline relevance metadata**

```python
def test_headline_exposes_relevance_score_and_matched_aliases(monkeypatch) -> None:
    ...
    assert snapshot.headlines[0].relevance_score > 0.5
    assert "Bitcoin" in snapshot.headlines[0].matched_aliases
    assert snapshot.avg_relevance_score > 0
```

- [ ] **Step 3: Add failing tests for weighted sentiment aggregation**

```python
def test_sentiment_is_weighted_by_relevance(monkeypatch) -> None:
    ...
    assert snapshot.sentiment_score > 0
```

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_intel.py
```

Expected:
- new tests fail because relevance metadata and weighted filtering are not implemented yet

### Task 2: Implement Relevance Scoring And Snapshot Extensions

**Files:**
- Modify: `core/analysis/intel.py`
- Test: `tests/test_intel.py`

- [ ] **Step 1: Extend `NewsHeadline` and `MarketIntelSnapshot`**

```python
@dataclass
class NewsHeadline:
    ...
    relevance_score: float = 0.0
    matched_aliases: List[str] = None
```

```python
@dataclass
class MarketIntelSnapshot:
    ...
    analysis_version: str = "v2"
    matched_aliases: List[str] = None
    avg_relevance_score: float = 0.0
    provider_counts: Dict[str, int] = None
```

- [ ] **Step 2: Add unified relevance helpers**

```python
def _find_alias_matches(text: str, aliases: Sequence[str]) -> List[str]:
    ...


def _score_article_relevance(article: Dict[str, Any], aliases: Sequence[str]) -> Tuple[float, List[str]]:
    ...
```

- [ ] **Step 3: Apply relevance filtering to all providers and weight aggregation**

```python
relevance_score, matched_aliases = self._score_article_relevance(item, aliases)
if relevance_score < self._min_relevance_threshold(aliases):
    continue
```

```python
weight = max(0.2, relevance_score)
weighted_sentiment_total += sentiment * weight
weight_total += weight
```

- [ ] **Step 4: Run focused tests**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_intel.py
```

Expected:
- `tests/test_intel.py` passes

### Task 3: Verify The Whole Project Stays Green

**Files:**
- Modify: `docs/SESSION_STATE.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/NEXT_STEP.md`

- [ ] **Step 1: Run the full suite**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q
```

Expected:
- full suite passes

- [ ] **Step 2: Update handoff docs**

Document:
- intel relevance scoring now applies to all providers
- snapshot/headline contract extensions
- next stage target
