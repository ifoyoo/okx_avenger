# TP/SL Redesign Design

## Goal

Rebuild take-profit / stop-loss handling so the project has one protection contract that is shared by strategy output, execution attach orders, and backtest exits.

## Current Problems

- `TradeSignal.protection` currently carries execution-shaped targets instead of rule intent.
- Execution and backtest do not consume the same semantics.
- Backtest ignores strategy protection entirely.
- `ratio` appears in runtime examples/tests but strategy only supports `percent`.
- The existing runtime `ProtectionMonitor` models a different threshold system and is not part of the main trading flow.

## Design

### Canonical protection contract

- Keep `ProtectionRule` as the user-facing rule shape from `.env` defaults and `watchlist.json` overrides.
- Change `TradeSignal.protection` to carry rule intent, not resolved exchange payload.
- Introduce `ResolvedTradeProtection` as the execution/backtest-only shape containing resolved `ProtectionTarget` values.

### Supported modes

- `percent`
  - Entry-relative percentage move.
  - Keep OKX ratio attach-order support.
- `price`
  - Absolute trigger price.
- `atr`
  - Entry price plus/minus `ATR * value`.
- `rr`
  - Take-profit only.
  - Uses the resolved stop-loss distance as `1R`, then sets TP to `entry +/- stop_distance * value`.

### Normalization rules

- Normalize `ratio`, `pct`, and `percentage` to `percent`.
- Normalize disabled synonyms to `disabled`.
- Reject inactive or incomplete rules during resolution instead of carrying half-valid targets downstream.

### Resolution flow

1. `build_protection_settings()` parses defaults/overrides into normalized `ProtectionRule`s.
2. Strategy copies active rules into `TradeSignal.protection`.
3. Execution resolves rules against planned entry reference price and ATR.
4. Backtest resolves the same rules against actual entry execution price and signal-time ATR.

### Backtest behavior

- After a position is opened, evaluate TP/SL on the same execution bar.
- If both TP and SL are touched in one bar, prefer stop-loss as the conservative outcome.
- Exit reasons become `take_profit` / `stop_loss` when protection fires.

### Non-goals

- No trailing stop / break-even / scale-out in this round.
- No separate legacy threshold system expansion.
- No extra configuration surface beyond the current defaults and watchlist `protection` object.
