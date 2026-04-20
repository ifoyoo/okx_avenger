# Backtest Parity And Position Sizing Design

## Goal

Make CLI backtests reflect the live strategy gate path closely enough to produce real trades, and make `max_position` mean what the runtime config says it means.

## Current Problems

- CLI backtests fetch only the entry timeframe and drop `higher_timeframes`, so the strategy runs without the `1H` gate that the live engine always supplies.
- `run_backtest_from_features()` already supports `higher_timeframe_features`, but the CLI aggregation path never passes them through.
- `PositionSizer` always applies a final hard cap of `0.05`, which can flatten larger per-market `max_position` values even when risk and balance budgets allow them.
- `Strategy.generate_signal()` hardcodes `trend_bias=HOLD`, so the higher-timeframe gate direction never reaches the sizing layer.

## Recommended Design

### Backtest data parity

- Keep the current CLI backtest structure.
- Add a helper that fetches each requested higher timeframe into a `{timeframe: DataFrame}` mapping.
- Thread that mapping through `_run_backtest_entry()` and `_run_single_backtest()` into `run_backtest_from_features()`.
- Default missing `higher_timeframes` to `("1H",)` to stay aligned with runtime/watchlist behavior.

### Position sizing semantics

- Keep balance-risk and initial-risk caps exactly as they are.
- Change the final size cap so it is derived from the risk-adjusted `base` size instead of the global fixed `0.05`.
- Preserve the existing short multiplier by scaling the final cap for sells.

### Gate-to-sizing integration

- Derive `trend_bias` from `gate_decision` inside `Strategy.generate_signal()`.
- Map bullish gate to `BUY`, bearish gate to `SELL`, and mixed/no-trade to `HOLD`.
- Continue ignoring legacy higher-timeframe objective notes for sizing bias; only the validated gate result should drive the bias.

## Testing Strategy

- Add CLI backtest regression tests proving record collection and tuning both pass `higher_timeframe_features` into the runner.
- Add a position sizing regression test proving a larger allowed `max_position` is no longer clipped to `0.05`.
- Update the strategy-core regression test so it proves the sizing layer receives gate-derived bias.

## Non-goals

- No attempt to replay the full live market-analysis or LLM path inside the backtester in this round.
- No redesign of template logic or higher-timeframe gate rules.
- No changes to live execution sizing beyond fixing the dormant gate bias and the final cap semantics.
