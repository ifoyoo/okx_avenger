# Notification Critical-Only Design

## Goal

Shrink Telegram notifications so they behave like an alert channel instead of a runtime feed.

## Current Problems

- `order_submitted` still fires for real runtime orders, which keeps mobile notifications noisy.
- Successful fill and live-pending submission are already different execution states, but notifications compress them into the same "good news" channel.
- `NOTIFY_LEVEL=orders` and `NOTIFY_LEVEL=all` imply that success broadcasts are still a supported behavior, which no longer matches the desired operating mode.

## Recommended Design

### Event scope

Runtime notifications should only keep events that require human attention:

- `runtime_error`
- `trade_blocked`
- `order_failed`

`order_submitted` should stop being published from the runtime path.

### Level semantics

- `critical`
  - send `runtime_error`, `trade_blocked`, `order_failed`
- `orders`
  - normalize to `critical`
- `all`
  - normalize to `critical`

This keeps old config values from breaking while removing the behavior difference that created noise.

### Runtime integration

- `cli_app/runtime_execution.py` should no longer emit `order_submitted`.
- Success-path runtime counters and logs stay unchanged; only Telegram delivery changes.
- Failed / blocked / runtime-exception notifications stay exactly as they are today.

### Message design

- Keep the current compact three-line rendering for alert events.
- Do not add a replacement success message in this round.

### Documentation impact

- README examples should stop recommending `NOTIFY_LEVEL=orders`.
- Decision and session docs should describe Telegram as critical-only alerting.

## Non-goals

- No new notification transport.
- No filled-vs-pending success split.
- No new config switch for success notifications.
