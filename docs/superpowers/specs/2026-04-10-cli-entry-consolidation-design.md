# CLI Entry Consolidation Design

## Summary

This design removes the legacy `main.py` entry path and keeps `cli.py` as the only real application entrypoint. The shell launcher `okx` remains a thin wrapper around `cli.py`. The Rich startup screen, confirmation prompt, duplicate scheduler flow, and duplicate runtime assembly in `main.py` are removed entirely.

The goal is not to redesign trading behavior. The goal is to collapse entrypoint responsibility to one codepath so startup behavior, heartbeat updates, logging, and command dispatch are defined in a single place.

## Goals

- Make `cli.py` the only supported Python entrypoint.
- Keep `okx` as a thin launcher that delegates to `cli.py`.
- Remove all startup UI and interactive confirmation behavior.
- Remove the duplicate runtime assembly and scheduling logic from `main.py`.
- Preserve existing CLI subcommands and behavior in `cli.py`.
- Keep this refactor limited to entrypoint consolidation and related tests.

## Non-Goals

- No strategy, execution, risk, analysis, or config model refactor.
- No README rewrite in this round.
- No backward-compatible dual-entry architecture.
- No new launcher UX, dashboard, or alternate startup mode.

## Current State

The repository currently has three user-visible startup surfaces:

1. `okx`
   - A shell wrapper that already delegates to `cli.py`.
2. `cli.py`
   - A full CLI with `once`, `run`, `status`, `config-check`, `strategies`, and `backtest`.
   - Owns runtime assembly, execution loop, heartbeat writing, and command dispatch.
3. `main.py`
   - A second runtime entry path with its own scheduler, startup UI, confirmation prompt, display helpers, notifier wiring, and runtime assembly.

This creates two problems:

- Behavior drift risk: `main.py` and `cli.py` can evolve differently even when they trigger the same trading engine.
- Maintenance drag: fixes to runtime orchestration must be reasoned about in two different files.

## Chosen Direction

The chosen direction is the hard cutover:

- Delete `main.py` as a real runtime path.
- Do not keep a forwarding shim from `main.py` to `cli.py`.
- Treat `cli.py` and `okx` as the only supported startup surfaces after the refactor.

This is intentionally stricter than keeping a compatibility wrapper. The point of this change is to remove the second path, not hide it behind a redirect.

## Architecture

### Entrypoint Ownership

After the refactor:

- `cli.py` owns all Python-side startup and command dispatch.
- `okx` remains a shell convenience wrapper and nothing more.
- `main.py` is removed from the supported runtime architecture.

There is one execution tree:

`okx` or `python cli.py ...` -> `cli.main()` -> parser dispatch -> runtime assembly -> command handler

### Runtime Responsibilities

`cli.py` remains responsible for:

- building the runtime bundle
- configuring logging
- resolving watchlist entries
- running one cycle or looping with heartbeat updates
- exposing status/config/backtest/strategy commands

No other file should own an alternate scheduler, startup confirmation flow, or duplicate runtime wiring.

### Startup Experience

The startup experience becomes intentionally plain:

- no Rich logo
- no centered information panels
- no `y` confirmation gate
- no separate decorative startup mode

Startup should begin immediately when the chosen command is invoked, with only normal CLI/log output.

## File-Level Changes

### `cli.py`

Keep and stabilize as the single real entrypoint.

Responsibilities after refactor:

- parser construction
- command dispatch
- runtime bundle creation and cleanup
- heartbeat persistence
- once/run/status/config-check/strategies/backtest handlers

This file may receive small internal cleanup if needed, but the refactor should avoid expanding its scope beyond entry orchestration.

### `okx`

Keep as a thin wrapper around `cli.py`.

Responsibilities after refactor:

- choose the local virtualenv Python if present
- otherwise fall back to `python3`
- execute `cli.py` with the original CLI args

No behavioral changes are required unless tests reveal ambiguity in the current wrapper.

### `main.py`

Remove from the runtime architecture.

This means deleting:

- `_confirm_launch`
- Rich startup rendering helpers
- the independent `schedule` loop
- duplicate instrument rendering and display helpers
- duplicate notifier/protection monitor setup at the entry layer
- the `main()` startup path itself

If full deletion causes repository-level friction during implementation, the acceptable fallback is an extremely small stub that immediately exits with a clear error instructing the user to use `./okx` or `python cli.py`. That fallback is second choice; the preferred result is deleting `main.py`.

## Behavior Changes

### Supported Commands

Supported execution forms after refactor:

- `./okx once ...`
- `./okx run ...`
- `./okx status`
- `python cli.py once ...`
- `python cli.py run ...`

Unsupported execution form after refactor:

- `python main.py`

### Logging and Heartbeat

Heartbeat ownership stays in `cli.py`. The refactor must not move heartbeat writing elsewhere.

Expected invariant:

- `once` writes `running` then `idle` or `error`
- `run` writes `running` per cycle and updates to `idle`, `error`, or `stopped`

The removal of `main.py` must not change this behavior.

## Error Handling

### Removed Path Failures

If `main.py` is fully deleted, a direct `python main.py` invocation will fail at the OS level because the file no longer exists. This is acceptable because the project is intentionally dropping that entrypoint.

If implementation temporarily keeps a minimal stub instead of deleting the file, the stub must:

- do no runtime setup
- do no implicit forwarding
- fail immediately with a clear instruction to use `./okx` or `python cli.py`

### Runtime Command Failures

Existing `cli.py` command error behavior remains the source of truth. The refactor should not add a second error-reporting style.

## Testing Strategy

### Existing Tests To Keep Passing

- `tests/test_cli_parser.py`
- `tests/test_cli_runtime_heartbeat.py`
- any existing CLI-related backtest tests that already exercise `cli.py`

### New Tests To Add

1. Entry ownership test
   - Assert that the launcher script `okx` still executes `cli.py`, not `main.py`.
2. Main path removal test
   - If `main.py` is deleted, assert the repository no longer contains a runtime entry implementation there.
   - If a stub is kept, assert it fails fast and does not implement its own scheduler or runtime setup.
3. CLI dispatch test
   - Add a focused unit test around `cli.main(...)` command dispatch with monkeypatched handlers, so the single-entry architecture is explicit in tests without requiring network access.

### Manual Verification

- Run `python cli.py --help`
- Run `./okx --help`
- Run the existing CLI parser and heartbeat tests
- Run one safe command path that does not require live trading, such as parser-only coverage or a monkeypatched command invocation

## Risks

### Hidden Dependence On `main.py`

Someone may still be launching the app with `python main.py`. Removing the file is a breaking change. That break is intentional, but the implementation should confirm there is no internal code path importing `main.py`.

### Over-Refactoring `cli.py`

The work should not turn into a large CLI redesign. The change is about deleting a duplicate path, not rebuilding every command abstraction.

### Test Blind Spots

Current test coverage is stronger on parser and heartbeat behavior than on full entry dispatch. The implementation should add narrow tests that prove entry ownership without requiring live OKX access.

## Acceptance Criteria

The refactor is complete when all of the following are true:

1. `cli.py` is the only real Python entrypoint.
2. `okx` still launches `cli.py`.
3. `main.py` no longer contains an independent scheduler, startup UI, runtime assembly, or trading loop.
4. Startup no longer shows the Rich logo, centered panels, or the manual `y` confirmation gate.
5. Existing CLI parser and heartbeat behavior remains intact.
6. Entrypoint-related tests pass.

## Implementation Notes For The Next Step

The implementation plan should stay narrow:

- remove `main.py` runtime logic first
- keep `okx` unchanged unless verification shows it needs a small adjustment
- add focused tests for single-entry ownership
- run CLI-related verification only, then expand if needed

This change should be implemented as an entrypoint consolidation refactor, not as a broader product cleanup pass.
