# Unified Bidirectional Trend Strategy Design

## Goal

Replace the current mixed-signal trading behavior with a unified, non-symmetric bidirectional trend strategy that can run across all configured instruments using one rule set.

The target operating profile is:

- lower drawdown than the current setup
- moderate win-rate improvement
- keep enough upside capture to avoid turning the system into a low-variance but low-edge bot

## Chosen Constraints

- one unified rule set for all instruments
- bidirectional trading remains enabled
- strategy style is trend-following first, not mean-reversion first
- medium trade frequency, not ultra-selective and not hyper-active
- exits use fixed stop loss plus partial take-profit and break-even promotion
- same-direction scale-in is allowed once only
- default leverage is reduced from `10x` to `5x`

## Alternatives Considered

### 1. Symmetric bidirectional trend strategy

Use nearly mirrored long and short rules.

Pros:

- simple mental model
- simple implementation
- easier to explain in backtests

Cons:

- poor fit for the current instrument set
- short-side noise and squeezes likely raise drawdown
- tends to overtrade low-quality bearish setups

### 2. Non-symmetric bidirectional trend strategy

Use one framework, but make short-side entry stricter and smaller than long-side entry.

Pros:

- preserves two-way opportunity
- better fit for volatile alt contracts
- improves drawdown control without giving up all short exposure

Cons:

- more rules than a mirrored system
- requires explicit gate logic

### 3. Mixed trend plus range strategy

Keep both trend and box/range ideas, but rebalance with weights and arbitration.

Pros:

- keeps more trade opportunities
- less disruptive to current code shape

Cons:

- preserves the current structural conflict between trend and mean-reversion signals
- still depends too much on arbitration after conflicting signals are already generated
- harder to make behavior predictable

## Recommendation

Adopt option 2: a non-symmetric bidirectional trend strategy.

The current system mixes trend continuation, breakout, box oscillation, and reversal ideas in the same decision path. That creates conflicts that are structural, not just weighting problems. The new design fixes this by:

- gating direction first on higher timeframe trend
- allowing only trend-consistent intraday entry templates
- demoting or removing reversal-style triggers from primary entry logic
- keeping short exposure, but making it harder to qualify than long exposure

## Current Problems

- A support plugin can promote a `HOLD` base state into a live directional trade, and this is partly affected by plugin order.
- Trend, breakout, and range signals are evaluated together and then reconciled after the fact.
- Current live configuration is aggressive on leverage and scale-in.
- Daily-loss and consecutive-loss circuit breakers exist in code but are effectively disabled by current config.
- Backtest and live execution are not aligned closely enough, especially around protection, higher-timeframe context, and execution-side blocking.
- Multi-instrument runtime cycles reuse the same account snapshot across the whole scan, which can make later trades size off stale balance data.

## Strategy Architecture

The new strategy is organized into four layers.

### Layer 1: Higher-timeframe direction gate

`1H` decides whether the system is allowed to:

- open longs
- open shorts
- open nothing

No lower-timeframe setup can open a position unless this gate allows the side first.

### Layer 2: Lower-timeframe entry templates

`5m` can only trigger trades through explicit templates:

- trend pullback long
- trend breakout long
- trend pullback short
- trend breakdown short

There is no generic "any directional indicator can fire" path.

### Layer 3: Quality filters

Supporting signals do not create trades on their own. They only confirm, boost, or reject a qualifying template.

These filters include:

- volume quality
- breakout quality
- liquidity
- volatility regime
- stale data
- pending order duplication
- same-direction position cap

### Layer 4: Exit and account risk

Risk handling is not optional post-processing. It is part of the strategy contract:

- fixed initial stop
- partial take-profit
- break-even promotion
- one controlled add-on only
- daily-loss and consecutive-loss circuit breakers

## Higher-Timeframe Direction Gate

### Long gate

Allow long setups when all of the following hold:

- `ema_fast > ema_slow`
- `ema_fast` slope is positive over the recent lookback
- `RSI >= 52`

Strength grading:

- if `ADX >= 18`, both pullback and breakout long templates are allowed
- if `ADX < 18` but the other conditions still hold, only pullback long setups are allowed

### Short gate

Allow short setups only when all of the following hold:

- `ema_fast < ema_slow`
- `ema_fast` slope is negative over the recent lookback
- `RSI <= 45`
- `ADX >= 20`

This is intentionally stricter than the long gate.

### No-trade gate

If `1H` trend is mixed, weak, or directionally ambiguous:

- do not open new positions
- demote all `5m` signals to observation only

## Lower-Timeframe Entry Templates

### Long template A: trend pullback long

Requirements:

- `1H` long gate passes
- `5m ema_fast > ema_slow`
- price pulls back near `ema_fast` or `ema_slow`
- pullback happens on neutral or shrinking volume
- price reclaims `ema_fast` or breaks the prior micro swing high
- `5m RSI` is preferably in a moderate range such as `45-62`

Intent:

- buy continuation after controlled weakness
- avoid chasing already extended impulse candles

### Long template B: trend breakout long

Requirements:

- `1H` long gate passes with breakout permission
- `5m` shows compression or clear consolidation
- price breaks above the recent local range or 20-bar high
- breakout is supported by volume confirmation
- setup is rejected if lower-timeframe momentum is already overextended

Intent:

- preserve upside participation in strong expansion moves

### Short template A: trend pullback short

Requirements:

- `1H` short gate passes
- `5m ema_fast < ema_slow`
- price retraces into `ema_fast` or `ema_slow` but fails to reclaim structure
- retrace is not a strong high-volume reclaim
- price rotates back below `ema_fast` or breaks the pullback confirmation low

Intent:

- short continuation after failed relief bounce

### Short template B: trend breakdown short

Requirements:

- `1H` short gate passes strongly
- `5m` shows consolidation or weak base
- price breaks below the recent local range or 20-bar low
- breakdown is supported by volume confirmation
- do not short after a single exhaustion candle with no structure

Intent:

- keep short exposure only for clean continuation conditions

## Signal and Plugin Role Changes

### Keep as core or strong confirmation

- `bull_trend`
- `shrink_pullback`
- `volume_breakout`
- `ma_golden_cross`
- `volume_pressure`
- `volatility_breakout`

### Keep, but downgrade

- `one_yang_three_yin`
  - long-side confirmation only
  - never a standalone entry trigger

### Remove from primary trade initiation

- `box_oscillation`

### Demote to contextual only

- pure RSI extreme reads
- pure Bollinger upper/lower touch reactions

These may remain visible in notes or confidence adjustment, but they no longer create live entries by themselves.

## Fusion Rules

The fusion engine should change from "any directional plugin may promote action" to "template-led fusion."

Required behavior:

- if the higher-timeframe gate denies the side, final action must remain `HOLD`
- supporting plugins may not promote `HOLD` to a live trade unless a valid template already exists
- supporting plugins may only:
  - increase confidence
  - decrease confidence
  - veto a weak setup

This removes plugin-order sensitivity from the decision to open a position.

## Position Sizing

### Baseline

- reduce `DEFAULT_LEVERAGE` to `5`
- reduce `DEFAULT_MAX_POSITION` from `0.04` to `0.02`

### Initial risk target

Target initial trade risk at roughly `0.6%` of account equity.

The sizing layer should convert this through:

- stop distance
- leverage
- current volatility
- available balance constraints

### Directional asymmetry

Default short-side size should be smaller than long-side size.

Recommended initial rule:

- long template size multiplier: `1.0`
- short template size multiplier: `0.8`

## Exit Design

### Initial stop

Use a hard initial stop based on `1.1 ATR`.

- long: `entry - 1.1 ATR`
- short: `entry + 1.1 ATR`

### Partial take-profit structure

- `TP1` at `+1R`: close `40%`
- after `TP1`, move stop on the remainder to break-even plus execution buffer
- `TP2` at `+2R`: close another `40%`
- remaining `20%` becomes the runner

### Runner management

The last `20%` should not use a distant fixed target. Manage it with a trailing structure such as:

- `5m ema_fast`
- or recent short-cycle swing structure

The goal is to preserve upside convexity in strong trends.

## Same-Direction Scale-In

Allow one scale-in only.

Rules:

- never add to a losing position
- scale-in is only allowed after the original trade has proven itself
- preferred trigger is after `TP1`, or at minimum near `+0.8R`
- the original stop must already be moved close to or above break-even before scale-in
- scale-in size should be about `30%-35%` of the initial position

Recommended total same-direction cap:

- total position size after scale-in must not exceed `1.35x` initial size

This replaces the current much more aggressive same-direction expansion behavior.

## Account-Level Risk Controls

Enable and use the circuit-breaker logic already present in code.

Recommended initial defaults:

- `RISK_DAILY_LOSS_LIMIT_PCT=0.02`
- `RISK_CONSECUTIVE_LOSS_LIMIT=3`
- `RISK_CONSECUTIVE_COOLDOWN_MINUTES=360`

Pending order handling:

- keep pending-order TTL behavior
- keep current-cycle block after stale order cancelation
- do not re-enter in the same cycle after stale-order cleanup

## Required Runtime and Backtest Consistency Fixes

These are part of the design, not optional cleanup.

### 1. Backtest/live protection parity

Backtest must use the same protection intent as live:

- same stop logic
- same take-profit logic
- same break-even promotion rules

### 2. Backtest/higher-timeframe parity

Backtest must evaluate the same higher-timeframe direction gate used in live mode.

### 3. Account snapshot freshness

In multi-instrument runtime cycles, fetch a fresh account snapshot before each instrument decision or at least before each instrument execution path.

Do not size all entries in one cycle from a single stale balance snapshot.

### 4. Decision logging clarity

Separate the following in logged records:

- `analysis_action`
- `gated_action`
- `final_strategy_action`

This avoids mixing deterministic analysis opinion with the actual executable action.

### 5. Protection OCO gap reduction

Live mode should keep the single exchange OCO reconciler, but it should call `enforce()` immediately after a successful fill path to reduce the gap between fill and protection placement.

## Config Changes

Recommended initial config direction:

```ini
DEFAULT_LEVERAGE=5
DEFAULT_MAX_POSITION=0.02
EXECUTION_ALLOW_SAME_DIRECTION_SCALE_IN=true
EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER=1.35

RISK_DAILY_LOSS_LIMIT_PCT=0.02
RISK_CONSECUTIVE_LOSS_LIMIT=3
RISK_CONSECUTIVE_COOLDOWN_MINUTES=360
```

Protection defaults should move away from the current "fixed UPL ratio only" behavior and align with the new R-based exit flow. The strategy contract already supports richer protection rules, so implementation should use that contract instead of keeping a purely static fixed-ratio mindset.

## Watchlist Contract

The watchlist format should remain unified, but the runtime should make better use of fields that already exist:

- `timeframe`
- `higher_timeframes`
- `protection`
- `news_query`
- `news_coin_id`
- `news_aliases`

The current file uses only `max_position`. That is acceptable, but the implementation should preserve per-instrument overrides for future use.

## Error Handling

- if the higher-timeframe gate cannot be evaluated, fail closed to `HOLD`
- if required ATR or structure data is missing, fail closed to `HOLD`
- if protection state cannot be resolved for a live trade, block execution rather than running unprotected
- if account snapshot refresh fails, use the previous snapshot only for observation, not for fresh live sizing
- if immediate post-fill OCO enforcement fails, emit a clear high-severity runtime event

## Non-Goals

- no per-instrument bespoke strategy logic
- no return to mixed range-first trading
- no unlimited pyramiding
- no LLM-led directional trading
- no attempt to maximize trade count

## Success Criteria

The redesign is considered successful if it produces all of the following compared with the current live behavior:

- fewer structurally conflicting signals
- smaller average adverse move per trade
- better stability in win rate
- lower drawdown under comparable market conditions
- preserved participation in clean breakout and continuation trends

## Validation and Testing

### Unit tests

- higher-timeframe direction gate decisions
- template qualification for all four templates
- plugin behavior when base state is `HOLD`
- asymmetric short-side sizing
- partial take-profit and break-even promotion
- one-time scale-in guardrails

### Integration tests

- runtime cycle with fresh account snapshot per instrument
- live execution path with immediate post-fill protection enforcement
- blocked execution on stale data, stale pending orders, and gate denial
- decision logging with separated `analysis_action`, `gated_action`, and `final_strategy_action`

### Backtest regression tests

- verify backtest uses higher-timeframe gate
- verify backtest applies the same protection contract as live
- verify backtest exits reflect partial take-profit and runner behavior

## Rollout

### Phase 1

- implement gate plus template structure
- disable range-first primary triggers
- reduce leverage and same-direction expansion

### Phase 2

- align backtest with live strategy contract
- add fresh account snapshot handling
- add richer decision logging

### Phase 3

- tune thresholds only after the new architecture is live in backtest and dry-run with parity checks

## Summary

The redesign is intentionally less permissive than the current system, but it is not a "trade rarely" strategy. It keeps medium opportunity flow by preserving both pullback and breakout entries, while materially reducing low-quality reversals, noisy short entries, and oversized same-direction escalation.
