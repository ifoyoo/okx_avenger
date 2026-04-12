# Notification Refactor Design

## Goal

Refactor the notification module so it matches the current project reality: runtime execution is the only active path, Telegram is the only configured transport, and notification behavior should be driven by concrete runtime outcomes instead of a generic unused interface.

## Current Problems

- `core/utils/notifications.py` defines a Telegram notifier, but nothing in the runtime path calls it.
- README and config imply Telegram cooldown notifications exist, but the main CLI workflow does not build or use a notifier.
- Notification semantics are unclear: there is no current mapping from `NOTIFY_LEVEL` to concrete runtime events.
- The module is transport-shaped (`send(message)`) instead of runtime-shaped (`blocked trade`, `order placed`, `runtime error`).

## Recommended Design

### Canonical runtime-focused notification center

- Replace the current generic notifier usage model with a `NotificationCenter`.
- `NotificationCenter` owns:
  - level filtering
  - cooldown keys
  - event-to-message rendering
  - transport dispatch

### Event scope

Only support events that exist in the current runtime workflow:

- `runtime_error`
  - `run_once` / per-symbol execution raises an exception
- `trade_blocked`
  - a directional signal is blocked before order submission
- `order_submitted`
  - a real order is placed successfully
- `order_failed`
  - execution reaches the exchange but returns a failure

No “all logs go to Telegram” behavior in this round.

### Level semantics

- `critical`
  - send `runtime_error`, `trade_blocked`, `order_failed`
- `orders`
  - include `order_submitted`
- `all`
  - same as `orders` for now; keep as normalized alias for future expansion without inventing extra events now

### Runtime integration

- `build_runtime()` creates the notification center from `settings.notification`.
- `RuntimeBundle` carries the notification center.
- `cli_app/runtime_execution.py` emits notifications from `run_runtime_cycle()` because that is where per-instrument results are available.
- `cli_app/runtime_workflows.py` emits a top-level runtime error notification when `run_runtime_once()` or loop execution crashes.

### Transport boundary

- Keep Telegram as a transport implementation, not the core API.
- Transport receives a fully rendered message string and parse mode.
- Cooldown stays above transport so different transports share the same suppression logic.

### Non-goals

- No multi-channel routing.
- No persistence-backed notification queue.
- No notification delivery retries beyond the underlying HTTP request.
- No rewriting of loguru logging into the notification system.
