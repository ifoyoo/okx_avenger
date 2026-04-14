# UPL-Ratio Protection Direct Switch Design

## Goal

Switch runtime take-profit / stop-loss defaults from price-percentage semantics to OKX position PnL ratio semantics, add stale pending-order TTL handling, and make protection-order sync failures observable instead of silently assuming success.

## Current Problems

- The current runtime defaults use price move percentages, but the operator is watching OKX `uplRatio` / position return. This causes repeated misreads such as "TP should have hit" when price has not actually reached the configured trigger.
- Runtime logs already show that order frequency is currently suppressed by execution-side duplicate guards, especially same-direction position blocking and long-lived live pending orders.
- `ProtectionOrderManager` logs "create" / "amend" actions but does not validate whether OKX actually accepted the algo order.
- A live pending limit order can remain open for many hours and block fresh entries indefinitely, even when the original setup is stale.

## Design

### Direct semantic switch

- Runtime defaults move to explicit UPL-ratio naming:
  - `DEFAULT_TAKE_PROFIT_UPL_RATIO`
  - `DEFAULT_STOP_LOSS_UPL_RATIO`
- Runtime mainline behavior no longer treats `DEFAULT_TAKE_PROFIT_PCT` / `DEFAULT_STOP_LOSS_PCT` as the primary protection defaults.
- The direct-switch decision is intentional: the operator wants one canonical runtime meaning, not dual semantics.

### Default values

- Default take-profit UPL ratio: `0.20`
- Default stop-loss UPL ratio: `0.10`
- Default stale pending-order TTL: `60` minutes via `EXECUTION_PENDING_ORDER_TTL_MINUTES`

### Protection threshold meaning

- `take_profit_upl_ratio = 0.20` means close when position return reaches `+20%`.
- `stop_loss_upl_ratio = 0.10` means close when position return reaches `-10%`.
- This matches the operator's OKX-facing decision loop and removes the current mismatch between exchange UI and bot config.

### Trigger price conversion

- Runtime protection orders still need exchange trigger prices, so UPL ratios must be converted into price thresholds.
- Conversion uses leverage-aware entry-relative price math.

For a long position:

- `tp_trigger_px = entry_price * (1 + take_profit_upl_ratio / leverage)`
- `sl_trigger_px = entry_price * (1 - stop_loss_upl_ratio / leverage)`

For a short position:

- `tp_trigger_px = entry_price * (1 - take_profit_upl_ratio / leverage)`
- `sl_trigger_px = entry_price * (1 + stop_loss_upl_ratio / leverage)`

### Leverage source

- `ProtectionOrderManager` must use the leverage from the live OKX position payload (`entry["lever"]`) when building desired OCO/conditional protection orders.
- Attach-algo orders created at entry time must use the runtime execution leverage already carried by the trading engine (`DEFAULT_LEVERAGE` today).
- If leverage is missing or invalid, fall back to `1.0` instead of silently dividing by zero or creating impossible thresholds.

### Protection-order sync validation

- `ProtectionOrderManager._place_order()` and `_amend_order()` must validate the exchange response before treating the operation as successful.
- Validation must check:
  - top-level `error`
  - per-item `sCode` / `sMsg`
  - algo response `failCode` when present
- On failure, runtime must emit a clear structured error event, for example:
  - `event=protection_order_sync_failed`
- The log must include:
  - `inst_id`
  - operation type (`place` / `amend`)
  - relevant payload fields
  - exchange code / message
- This is an observability fix only; it does not change trade direction logic.

### Stale pending-order TTL handling

- Add `EXECUTION_PENDING_ORDER_TTL_MINUTES`.
- When execution detects a live pending normal order for the same instrument:
  - If the order age is within TTL, keep current behavior: block new entry.
  - If the order age exceeds TTL and the order is still completely unfilled (`accFillSz == 0`), cancel it first.
  - The current cycle remains blocked after cancelation and records a reason like "stale pending order canceled; retry next cycle".
  - Fresh evaluation and possible re-entry happen on the next cycle only.

### Pending-order cancellation guardrails

- Only auto-cancel orders that are all true:
  - `state == live`
  - `accFillSz == 0`
  - not `reduceOnly`
  - normal entry order, not protection algo order
  - age exceeds configured TTL
- Do not immediately place a replacement order in the same cycle.
- Do not touch exchange-side TP/SL algo orders through this TTL path.

### Trigger price type

- This round keeps `tpTriggerPxType` / `slTriggerPxType = "last"`.
- The current scope is semantic alignment plus observability and stale-order cleanup.
- `mark` / `index` trigger-source selection is explicitly deferred.

## Data Flow

1. Settings parsing reads `DEFAULT_TAKE_PROFIT_UPL_RATIO`, `DEFAULT_STOP_LOSS_UPL_RATIO`, and `EXECUTION_PENDING_ORDER_TTL_MINUTES`.
2. Runtime bundle construction creates `ProtectionThresholds` using UPL-ratio defaults, not price-percentage defaults.
3. Watchlist override normalization passes per-instrument UPL-ratio thresholds into the protection manager.
4. Entry-time attach protection resolves trigger prices from entry price and leverage-aware UPL conversion.
5. Position-sync OCO reconciliation resolves trigger prices from live position `avgPx` and exchange-reported `lever`.
6. Execution duplicate guard checks live pending orders.
7. Stale pending entries older than TTL are canceled, the current cycle is marked blocked, and the next cycle can evaluate a fresh order.

## File-Level Changes

### Configuration

- `config/settings.py`
  - add explicit UPL-ratio fields and TTL field
  - remove runtime dependence on old price-percentage names
  - validate new ratios in `[0, 1]`

### Runtime context and workflow

- `cli_app/context.py`
  - build protection manager from UPL-ratio defaults
- `cli_app/runtime_execution.py`
  - normalize watchlist protection overrides into UPL-ratio thresholds
  - update any helper naming that still implies price-percentage semantics

### Execution path

- `core/engine/trading.py`
  - extend pending-order duplicate guard so it can identify and cancel stale pending orders under TTL rules
  - keep current-cycle blocked after successful cancelation
- `core/engine/execution.py`
  - convert entry-time attach protection from UPL-ratio intent into price triggers using runtime leverage

### Protection order sync

- `core/engine/protection.py`
  - replace threshold fields with explicit UPL-ratio names such as `take_profit_upl_ratio` / `stop_loss_upl_ratio`
- `core/engine/protection_orders.py`
  - compute TP/SL triggers from `avgPx` and live position leverage
  - validate `place_algo_order()` / `amend_algo_order()` responses
  - emit explicit structured failure logs

### Documentation

- `README.md`
  - explain that runtime TP/SL defaults now follow OKX position return semantics
- `.env`
  - switch default names and values to UPL-ratio semantics

### Tests

- `tests/test_execution_clordid.py`
  - cover attach-algo price conversion from UPL-ratio semantics
- `tests/test_protection_order_manager.py`
  - cover leverage-aware OCO conversion and sync failure logging
- `tests/test_cli_runtime_workflows.py`
  - cover UPL-ratio threshold propagation
- `tests/test_cli_runtime_cycle.py`
  - cover stale pending-order cancel + blocked-this-cycle behavior
- `tests/test_settings_validation.py`
  - cover new env names, defaults, and validation
- add or extend targeted tests rather than broad integration rewrites

## Error Handling

- Invalid or missing leverage falls back to `1.0` and must log at warning level if the source value is malformed.
- Failed stale-order cancelation keeps the cycle blocked and logs the exchange error.
- Failed protection-order place/amend must never be logged as an unconditional success.
- No silent downgrade from UPL-ratio semantics back to price-percentage semantics.

## Non-Goals

- No dual-mode runtime support for both price-percentage and UPL-ratio semantics.
- No trigger-type switch to `mark` or `index` in this round.
- No aggressive same-cycle cancel-and-reenter behavior.
- No trailing stop, break-even, or partial scale-out changes.

## Rollout and Rollback

### Rollout

- Deploy config with:
  - `DEFAULT_TAKE_PROFIT_UPL_RATIO=0.20`
  - `DEFAULT_STOP_LOSS_UPL_RATIO=0.10`
  - `EXECUTION_PENDING_ORDER_TTL_MINUTES=60`
- After deploy, verify:
  - new positions receive leverage-aware protection prices
  - stale pending entry orders are canceled after TTL
  - protection sync failures are visible in logs

### Rollback

- If UPL-ratio semantics are rejected, restore the previous price-percentage settings and conversion flow.
- TTL-based stale-pending cleanup can remain independently if desired.
- Protection-order response validation should not be rolled back unless it causes a specific integration issue.

## Test Strategy

- Configuration tests for new env fields and defaults.
- Unit tests for long/short leverage-aware trigger-price conversion.
- Runtime-cycle tests for stale pending order cancellation and blocked-next-cycle semantics.
- Protection-order manager tests for exchange response failure handling.
- Regression coverage for existing duplicate-entry guards so same-direction and live-pending blocking still work after the TTL extension.
