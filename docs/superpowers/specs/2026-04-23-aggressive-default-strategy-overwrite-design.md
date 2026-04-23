# Aggressive Default Strategy Overwrite Design

## Goal

Replace the current conservative default trading behavior with a high-frequency, high-utilization default profile that opens more trades and uses meaningfully larger position size.

The target operating profile is:

- materially more live trade opportunities than the current default
- larger average utilized notional per entry
- tolerance for noisy lower-timeframe setups and countertrend entries
- keep only the hard safety rails that protect against stale data, duplicate orders, and catastrophic daily loss

## Chosen Constraints

- this overwrites the current default strategy behavior; there is no parallel `aggressive=true` mode in this round
- `5m` is the primary decision frame
- `1H` is no longer allowed to veto new entries
- manual `watchlist.json` remains the only universe source
- signal, template, and liquidity evaluation must use the latest confirmed candle rather than the currently-forming candle
- existing stale-data, pending-order, duplicate-order, and protection-order machinery stays in place

## Alternatives Considered

### 1. Keep the current gate architecture and only loosen thresholds

Pros:

- smallest code change
- easy to reason about
- preserves most existing tests

Cons:

- still leaves `1H` as the dominant choke point
- still leaves `entry_template` as a binary pass/fail gate
- still produces large `HOLD` clusters when the market is mixed or when a template barely misses

### 2. Remove hard higher-timeframe vetoes and convert templates into boosters

Pros:

- directly addresses the current root cause of low trade frequency
- keeps the existing strategy structure recognizable
- raises trade count without rewriting the engine into a different product

Cons:

- more noisy trades than the current default
- requires re-locking test expectations around `HOLD` behavior
- needs tighter observability so operators can see when a trade came from a weaker fast-path

### 3. Replace the current strategy with a pure lower-timeframe momentum scalper

Pros:

- maximum aggressiveness
- simplest mental model for entry logic
- highest potential trade frequency

Cons:

- throws away too much of the existing strategy code
- likely to overtrade badly on volatile alts
- too disruptive for one change set because it combines a strategy rewrite with a behavior rewrite

## Recommendation

Adopt option 2.

The current strategy is not under-trading because a single numeric threshold is slightly too high. It is under-trading because the architecture is still shaped around hard vetoes:

- `1H` can force `no_trade`
- missing `entry_template` forces `HOLD`
- liquidity is evaluated on the currently-forming `5m` candle, which can briefly look empty even when the previous closed candle was liquid

The aggressive default should therefore keep the current engine shape, but remove those hard vetoes and treat them as soft quality inputs instead.

## Current Problems

- `Strategy.generate_signal()` currently forces `HOLD` whenever `entry_template is None`, even if lower-timeframe objective signals and the analysis view already agree on direction.
- `evaluate_higher_timeframe_gate()` still decides whether the strategy is allowed to trade at all, which makes `1H` directional ambiguity collapse live frequency.
- `liquidity_snapshot()` evaluates the latest row in the feature frame. Because OKX returns the currently-forming candle too, a fresh `5m` bar can show tiny interim volume and trip false liquidity blocks.
- This false-liquidity pattern is real in the current code path. For example, on `2026-04-23`:
  - `WLFI-USDT-SWAP` previous closed `5m` candle had about `33,706 USD` notional, while the currently-forming candle briefly showed about `929 USD`
  - `XRP-USDT-SWAP` previous closed `5m` candle had about `501,548 USD` notional, while the currently-forming candle briefly showed about `885 USD`
- The checked-in default watchlist is tilted toward low-liquidity hotspot contracts (`PUMP`, `WLFI`) instead of a mixed liquid core.
- Current risk defaults are tuned for moderate participation, not for the user-requested high-aggression profile.

## Strategy Architecture

The aggressive default keeps the existing runtime and execution pipeline, but changes how entries are qualified.

### Layer 1: Universe and market selection

- Keep manual `watchlist.json`.
- Rewrite the checked-in default watchlist away from the current hotspot-heavy set.
- The new checked-in default universe should be:
  - `BTC-USDT-SWAP`
  - `ETH-USDT-SWAP`
  - `SOL-USDT-SWAP`
  - `XRP-USDT-SWAP`
  - `DOGE-USDT-SWAP`
  - `SUI-USDT-SWAP`
- This is the practical mixed pool for this round:
  - `BTC` and `ETH` provide the high-liquidity anchor
  - `SOL`, `XRP`, `DOGE`, and `SUI` provide the higher-beta aggressive layer
- Remove `PUMP-USDT-SWAP` and `WLFI-USDT-SWAP` from the checked-in default file. They remain manually supported, but they should not define the default operating profile.

### Layer 2: Candle selection contract

- Introduce an explicit notion of the signal candle.
- For signal generation, template matching, and liquidity checks:
  - use the latest confirmed candle if the feed exposes a confirmed row
  - otherwise, when the latest candle is still in progress, use the previous row
- Data freshness checks may still inspect the freshest timestamp available, but entry logic must not rely on a half-built candle.

This change is required for correctness, not only for aggressiveness. Without it, the strategy can block otherwise valid setups during the first seconds of every new `5m` bar.

### Layer 3: Higher-timeframe context

- Keep collecting `1H` data.
- Remove `1H` as an entry veto.
- `1H` remains descriptive context only:
  - include it in notes and decision logs
  - allow it to inform human-readable explanations
  - do not auto-block longs because `1H` says bearish
  - do not auto-block shorts because `1H` says bullish
- In this round, `1H` should not apply an automatic countertrend penalty either. The user explicitly chose the highest-aggression profile, so the lower timeframe must be allowed to act on its own.

### Layer 4: Entry qualification

- Remove the current rule that forces `HOLD` when `entry_template is None`.
- Keep entry templates, but change their role:
  - matching template = confidence and size booster
  - missing template = allowed, but weaker quality tier
- The new directional contract becomes:
  - if lower-timeframe fusion is directional and liquidity passes, a trade may proceed even without a template
  - if a template exists, raise the confidence floor and allow larger size within the same risk budget
- This creates two entry quality tiers:
  - `template-qualified`
  - `fast-path directional`

### Layer 5: Liquidity policy

- Continue to block truly bad liquidity.
- Lower the default thresholds from the current conservative values:
  - `MIN_LIQUIDITY_RATIO`: `0.20 -> 0.10`
  - `MIN_NOTIONAL_USD`: `2000 -> 1000`
  - latest-bar emergency floor: effectively `1000 -> 500`
- Apply those thresholds to the confirmed signal candle, not the live partial candle.
- Do not add symbol-specific liquidity exemptions in this round. The aggressive profile should still have one global minimum floor.

### Layer 6: Sizing and same-direction expansion

- Increase capital utilization defaults:
  - `BALANCE_USAGE_RATIO`: `0.70 -> 0.90`
  - `DEFAULT_LEVERAGE`: `5 -> 8`
- Increase same-direction expansion capacity:
  - `EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER`: `1.35 -> 2.20`
- Keep the current execution rule based on total same-direction size cap, rather than adding a separate staged add-count system in this round.
- Size behavior by entry tier:
  - `template-qualified` entries can use the full aggressive sizing path
  - `fast-path directional` entries should use a modest size discount rather than a full block

### Layer 7: Account risk profile

- Raise the account-level circuit breaker to match the chosen aggression:
  - `RISK_DAILY_LOSS_LIMIT_PCT`: `0.02 -> 0.08`
  - `RISK_CONSECUTIVE_LOSS_LIMIT`: `3 -> 6`
  - `RISK_CONSECUTIVE_COOLDOWN_MINUTES`: `360 -> 90`
- Keep daily-loss and consecutive-loss protection enabled. High aggression is not the same as no kill switch.
- Do not redesign TP/SL semantics in this round. Existing exchange protection semantics remain unchanged.

## Runtime And Logging Changes

- Runtime result lines should make the new entry tier visible:
  - `entry=template-qualified`
  - `entry=fast-path`
- Decision logs should record:
  - whether a template was present
  - whether the signal candle was the latest confirmed row or a fallback previous row
  - the higher-timeframe context note without using it as `gated_action`
- This avoids a repeat of the current situation where everything only appears as generic `HOLD` with no obvious explanation of which gate actually killed the trade.

## Testing Strategy

- Add strategy-core tests proving a directional fusion result can survive when `entry_template is None`.
- Add regression tests proving opposite `1H` context no longer forces `HOLD`.
- Add signal/liquidity tests proving the strategy uses the confirmed candle instead of the currently-forming candle.
- Add config tests locking the new aggressive defaults.
- Add runtime-facing tests proving result lines expose the new entry tier and no longer describe `1H` as a hard gate.
- Keep existing stale-data, pending-order, and duplicate-order tests unchanged; those guards are still required.

## Non-goals

- No background process supervision or auto-restart for `./okx run`.
- No automatic watchlist rotation or scoring-based universe selection.
- No LLM or market-intel redesign in this round.
- No exchange execution API redesign.
- No overhaul of TP/SL rule semantics beyond preserving compatibility with the current protection chain.
