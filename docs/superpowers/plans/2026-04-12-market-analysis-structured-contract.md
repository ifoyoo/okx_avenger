# Market Analysis Structured Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor deterministic market analysis so `MarketAnalyzer` produces stable structured assessments for trend, momentum, levels, and risk while preserving the existing `MarketAnalysis` compatibility fields.

**Architecture:** Keep `core/analysis/market.py` as the public entry point, but change its internal flow from “raw indicators -> text + a few scalar fields” to “assessment objects -> compatibility backfill -> text rendering”. Tests first lock the new contract, then implementation backfills old fields from the new structures.

**Tech Stack:** Python, dataclasses, pandas, existing market snapshot/performance helpers, pytest

---

### Task 1: Lock The Structured Contract With Failing Tests

**Files:**
- Modify: `tests/test_market_analyzer.py`

- [ ] **Step 1: Write the failing contract tests for structured assessments**

```python
def test_analysis_exposes_structured_assessments(analyzer, sample_features):
    result = analyzer.analyze(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        features=sample_features,
    )

    assert result.analysis_version == "v2"
    assert result.trend.direction in {"bullish", "bearish", "range"}
    assert 0 <= result.trend.strength <= 1
    assert -1 <= result.momentum.score <= 1
    assert isinstance(result.levels.supports, list)
    assert isinstance(result.risk.factors, list)
```

```python
def test_legacy_fields_are_backfilled_from_assessments(analyzer, sample_features):
    result = analyzer.analyze(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        features=sample_features,
    )

    assert result.trend_strength == result.trend.strength
    assert result.momentum_score == result.momentum.score
    assert result.support_levels == result.levels.supports
    assert result.resistance_levels == result.levels.resistances
    assert result.risk_factors == result.risk.factors
```

- [ ] **Step 2: Write the failing consistency tests for trend and text**

```python
def test_bearish_sample_produces_bearish_trend_label(analyzer, sample_features):
    df = sample_features.copy()
    df["close"] = [200 - i * 0.8 for i in range(len(df))]
    df["ema_fast"] = [200 - i * 0.9 for i in range(len(df))]
    df["ema_slow"] = [200 - i * 0.6 for i in range(len(df))]
    df["adx"] = 35.0
    df["adx_pos"] = 12.0
    df["adx_neg"] = 28.0

    result = analyzer.analyze(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        features=df,
    )

    assert result.trend.direction == "bearish"
    assert "下跌" in result.text or "看跌" in result.text
```

- [ ] **Step 3: Run the focused tests to verify they fail**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_market_analyzer.py
```

Expected:
- tests fail because `MarketAnalysis` does not yet expose `analysis_version`, `trend`, `momentum`, `levels`, or `risk`

- [ ] **Step 4: Commit the red tests**

```bash
git add tests/test_market_analyzer.py
git commit -m "test: lock market analysis structured contract"
```

### Task 2: Add Structured Assessment Dataclasses And Compatibility Backfill

**Files:**
- Modify: `core/analysis/market.py`
- Test: `tests/test_market_analyzer.py`

- [ ] **Step 1: Add the assessment dataclasses and extend `MarketAnalysis`**

```python
@dataclass
class TrendAssessment:
    direction: str = "range"
    strength: float = 0.0
    label: str = ""
    ema_gap_pct: float = 0.0
    adx: float = 0.0
    higher_timeframe_alignment: float = 0.0


@dataclass
class MomentumAssessment:
    score: float = 0.0
    label: str = "neutral"
    rsi: float = 50.0
    macd_bias: str = "neutral"
    stoch_bias: str = "neutral"
    williams_bias: str = "neutral"
```

```python
@dataclass
class MarketAnalysis:
    text: str
    summary: str
    history_hint: str
    trend_strength: float = 0.5
    momentum_score: float = 0.0
    support_levels: List[float] = None
    resistance_levels: List[float] = None
    risk_factors: List[str] = None
    trend: TrendAssessment = None
    momentum: MomentumAssessment = None
    levels: LevelAssessment = None
    risk: RiskAssessment = None
    analysis_version: str = "v2"
```

- [ ] **Step 2: Change `analyze()` to build assessments first and backfill old fields**

```python
trend = self._assess_trend(features, higher_features)
momentum = self._assess_momentum(features)
levels = self._assess_levels(features)
risk = self._assess_risk(
    features=features,
    higher_features=higher_features,
    risk_note=risk_note,
    account_snapshot=account_snapshot,
    levels=levels,
)
```

```python
return MarketAnalysis(
    text=analysis_text,
    summary=summary_text,
    history_hint=history_hint,
    trend_strength=trend.strength,
    momentum_score=momentum.score,
    support_levels=levels.supports,
    resistance_levels=levels.resistances,
    risk_factors=risk.factors,
    trend=trend,
    momentum=momentum,
    levels=levels,
    risk=risk,
)
```

- [ ] **Step 3: Run focused tests to verify the contract passes**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_market_analyzer.py
```

Expected:
- the new structured-contract tests pass
- any remaining failures are from text rendering or heuristic drift

- [ ] **Step 4: Commit the compatibility-layer implementation**

```bash
git add core/analysis/market.py tests/test_market_analyzer.py
git commit -m "refactor: add structured market assessments"
```

### Task 3: Refine Trend, Momentum, Risk, And Text Rendering

**Files:**
- Modify: `core/analysis/market.py`
- Test: `tests/test_market_analyzer.py`

- [ ] **Step 1: Replace single-indicator trend scoring with multi-signal assessment**

```python
def _assess_trend(self, features, higher_features) -> TrendAssessment:
    latest = features.iloc[-1]
    ema_fast = float(latest.get("ema_fast", 0.0) or 0.0)
    ema_slow = float(latest.get("ema_slow", 0.0) or 0.0)
    adx = float(latest.get("adx", 0.0) or 0.0)
    adx_pos = float(latest.get("adx_pos", 0.0) or 0.0)
    adx_neg = float(latest.get("adx_neg", 0.0) or 0.0)
```

```python
    gap_pct = (ema_fast - ema_slow) / ema_slow if abs(ema_slow) > 1e-9 else 0.0
    di_bias = 1.0 if adx_pos > adx_neg else -1.0 if adx_neg > adx_pos else 0.0
    alignment = self._higher_timeframe_alignment(higher_features, gap_pct)
    raw_strength = min(abs(gap_pct) * 18.0, 0.55) + min(adx / 100.0, 0.35) + alignment * 0.1
    direction_score = (1.0 if gap_pct > 0 else -1.0 if gap_pct < 0 else 0.0) + di_bias * 0.6 + alignment * 0.5
    direction = "bullish" if direction_score > 0.35 else "bearish" if direction_score < -0.35 else "range"
    strength = max(0.0, min(1.0, raw_strength))
    label = self._trend_label(direction=direction, strength=strength, adx=adx, alignment=alignment)
    return TrendAssessment(
        direction=direction,
        strength=strength,
        label=label,
        ema_gap_pct=gap_pct,
        adx=adx,
        higher_timeframe_alignment=alignment,
    )
```

- [ ] **Step 2: Replace RSI-only momentum scoring with multi-indicator aggregation**

```python
def _assess_momentum(self, features) -> MomentumAssessment:
    latest = features.iloc[-1]
    rsi = float(latest.get("rsi", 50.0) or 50.0)
    macd = float(latest.get("macd", 0.0) or 0.0)
    macd_signal = float(latest.get("macd_signal", 0.0) or 0.0)
    stoch_k = float(latest.get("stoch_k", 50.0) or 50.0)
    williams_r = float(latest.get("williams_r", -50.0) or -50.0)
```

```python
    score = (
        self._normalize_rsi_signal(rsi) * 0.35
        + (0.25 if macd > macd_signal else -0.25 if macd < macd_signal else 0.0)
        + (0.2 if stoch_k >= 80 else -0.2 if stoch_k <= 20 else 0.0)
        + (0.2 if williams_r >= -20 else -0.2 if williams_r <= -80 else 0.0)
    )
    score = max(-1.0, min(1.0, score))
    label = (
        "overbought" if score >= 0.55 else
        "oversold" if score <= -0.55 else
        "bullish" if score > 0.15 else
        "bearish" if score < -0.15 else
        "neutral"
    )
    return MomentumAssessment(
        score=score,
        label=label,
        rsi=rsi,
        macd_bias="bullish" if macd > macd_signal else "bearish" if macd < macd_signal else "neutral",
        stoch_bias="overbought" if stoch_k >= 80 else "oversold" if stoch_k <= 20 else "neutral",
        williams_bias="overbought" if williams_r >= -20 else "oversold" if williams_r <= -80 else "neutral",
    )
```

- [ ] **Step 3: Make text rendering consume assessments instead of raw parallel logic**

```python
def _compose_analysis_text(
    self,
    *,
    inst_id: str,
    timeframe: str,
    latest: pd.Series,
    trend: TrendAssessment,
    momentum: MomentumAssessment,
    levels: LevelAssessment,
    risk: RiskAssessment,
    account_snapshot: Optional[Dict[str, float]],
) -> str:
    sections = [
        f"**交易对**：{inst_id} @ {timeframe}",
        f"**当前价格**：{float(latest.get('close', 0.0) or 0.0):.4f}",
        f"**趋势**：{trend.label}",
        f"**动量**：{momentum.label}（score={momentum.score:+.2f}, RSI={momentum.rsi:.1f}）",
    ]
    if levels.supports:
        sections.append("**支撑位**：" + " / ".join(f"{item:.4f}" for item in levels.supports))
    if levels.resistances:
        sections.append("**阻力位**：" + " / ".join(f"{item:.4f}" for item in levels.resistances))
    if risk.factors:
        sections.append("**风险**：" + "; ".join(risk.factors))
    return "\\n".join(sections)
```

- [ ] **Step 4: Run focused tests and then the full suite**

Run:
```bash
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q tests/test_market_analyzer.py
/Users/t/Desktop/Python/okx/.venv/bin/python -m pytest -q
```

Expected:
- focused tests pass
- full suite stays green

- [ ] **Step 5: Commit the refactor completion**

```bash
git add core/analysis/market.py tests/test_market_analyzer.py
git commit -m "refactor: stabilize deterministic market analysis"
```
