# UPL-Ratio Protection Direct Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch runtime TP/SL defaults to OKX `uplRatio` semantics, add stale pending-order TTL cleanup, and make protection-order sync failures explicit and observable.

**Architecture:** Replace runtime default protection fields with explicit UPL-ratio settings, propagate those thresholds through runtime and protection-sync paths, and convert them to exchange trigger prices using leverage-aware math. Extend the duplicate-order guard to cancel stale pending entry orders without re-entering in the same cycle, and harden protection-order sync by validating exchange responses instead of logging blind success.

**Tech Stack:** Python 3, Pydantic settings, OKX REST SDK wrapper, pytest, loguru

---

## File Map

- Modify: `config/settings.py`
  - Add explicit UPL-ratio defaults and pending-order TTL config.
- Modify: `cli_app/context.py`
  - Build the protection manager from UPL-ratio defaults.
- Modify: `cli_app/runtime_execution.py`
  - Normalize watchlist overrides into UPL-ratio thresholds.
- Modify: `core/engine/protection.py`
  - Rename threshold model fields to UPL-ratio semantics and keep enforcement logic coherent.
- Modify: `core/engine/protection_orders.py`
  - Convert UPL ratios to trigger prices with live position leverage and validate place/amend responses.
- Modify: `core/engine/execution.py`
  - Convert entry-time attach protection from UPL ratios to trigger prices using runtime leverage.
- Modify: `core/engine/trading.py`
  - Add stale pending-order TTL handling and blocked-this-cycle behavior.
- Modify: `README.md`
  - Document the new runtime TP/SL semantics and default values.
- Modify: `.env`
  - Replace old runtime default names with the new UPL-ratio defaults and TTL.
- Test: `tests/test_settings_validation.py`
- Test: `tests/test_cli_runtime_workflows.py`
- Test: `tests/test_execution_clordid.py`
- Test: `tests/test_protection_order_manager.py`
- Test: `tests/test_cli_runtime_cycle.py`
- Test: `tests/test_trading_pipeline.py`

### Task 1: Switch Runtime Config and Threshold Models to UPL Ratios

**Files:**
- Modify: `config/settings.py`
- Modify: `cli_app/context.py`
- Modify: `cli_app/runtime_execution.py`
- Modify: `core/engine/protection.py`
- Test: `tests/test_settings_validation.py`
- Test: `tests/test_cli_runtime_workflows.py`
- Test: `tests/test_cli_runtime_cycle.py`

- [ ] **Step 1: Write the failing config and runtime-threshold tests**

```python
# tests/test_settings_validation.py
def test_strategy_settings_accept_upl_ratio_defaults() -> None:
    settings = StrategySettings(
        DEFAULT_TAKE_PROFIT_UPL_RATIO=0.20,
        DEFAULT_STOP_LOSS_UPL_RATIO=0.10,
    )

    assert settings.default_take_profit_upl_ratio == 0.20
    assert settings.default_stop_loss_upl_ratio == 0.10


def test_runtime_settings_accept_pending_order_ttl_minutes() -> None:
    runtime = RuntimeSettings(EXECUTION_PENDING_ORDER_TTL_MINUTES=60)

    assert runtime.execution_pending_order_ttl_minutes == 60


def test_strategy_settings_reject_invalid_upl_ratio() -> None:
    with pytest.raises(ValidationError):
        StrategySettings(DEFAULT_TAKE_PROFIT_UPL_RATIO=1.2)
```

```python
# tests/test_cli_runtime_workflows.py
assert monitor.thresholds == [
    ("WLFI-USDT-SWAP", {"take_profit_upl_ratio": 0.05, "stop_loss_upl_ratio": 0.02})
]
```

```python
# tests/test_cli_runtime_cycle.py
assert monitor.thresholds == [
    ("BTC-USDT-SWAP", {"take_profit_upl_ratio": 0.04, "stop_loss_upl_ratio": 0.02})
]
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_settings_validation.py tests/test_cli_runtime_workflows.py tests/test_cli_runtime_cycle.py
```

Expected:

```text
FAIL ... default_take_profit_upl_ratio
FAIL ... execution_pending_order_ttl_minutes
FAIL ... take_profit_upl_ratio
```

- [ ] **Step 3: Implement the minimal settings and threshold-model rename**

```python
# config/settings.py
class StrategySettings(SettingsBase):
    balance_usage_ratio: float = Field(0.7, alias="BALANCE_USAGE_RATIO")
    default_leverage: float = Field(1.0, alias="DEFAULT_LEVERAGE")
    default_take_profit_upl_ratio: float = Field(0.20, alias="DEFAULT_TAKE_PROFIT_UPL_RATIO")
    default_stop_loss_upl_ratio: float = Field(0.10, alias="DEFAULT_STOP_LOSS_UPL_RATIO")
```

```python
# config/settings.py
class RuntimeSettings(SettingsBase):
    execution_pending_order_ttl_minutes: int = Field(60, alias="EXECUTION_PENDING_ORDER_TTL_MINUTES")
```

```python
# core/engine/protection.py
@dataclass
class ProtectionThresholds:
    take_profit_upl_ratio: float
    stop_loss_upl_ratio: float
```

```python
# cli_app/context.py
default_tp = max(0.0, float(settings.strategy.default_take_profit_upl_ratio or 0.0))
default_sl = max(0.0, float(settings.strategy.default_stop_loss_upl_ratio or 0.0))
```

```python
# cli_app/runtime_execution.py
monitor.set_inst_threshold(
    inst_id,
    {
        "take_profit_upl_ratio": _normalize_protection_pct(protection.get("take_profit"), default_tp),
        "stop_loss_upl_ratio": _normalize_protection_pct(protection.get("stop_loss"), default_sl),
    },
)
```

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_settings_validation.py tests/test_cli_runtime_workflows.py tests/test_cli_runtime_cycle.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit the config/threshold rename**

```bash
git add config/settings.py cli_app/context.py cli_app/runtime_execution.py core/engine/protection.py tests/test_settings_validation.py tests/test_cli_runtime_workflows.py tests/test_cli_runtime_cycle.py
git commit -m "refactor: switch runtime protection defaults to upl ratio"
```

### Task 2: Make Entry-Time and Position-Time Protection Leverage-Aware

**Files:**
- Modify: `core/engine/execution.py`
- Modify: `core/engine/trading.py`
- Modify: `core/engine/protection_orders.py`
- Test: `tests/test_execution_clordid.py`
- Test: `tests/test_protection_order_manager.py`
- Test: `tests/test_trading_pipeline.py`

- [ ] **Step 1: Write the failing leverage-aware protection tests**

```python
# tests/test_execution_clordid.py
def test_build_plan_resolves_attach_algo_orders_from_upl_ratio_protection() -> None:
    client = _DummyOKXClient()
    engine = ExecutionEngine(client)
    signal = TradeSignal(
        action=SignalAction.BUY,
        confidence=0.7,
        reason="x",
        size=0.01,
        protection=TradeProtection(
            take_profit=ProtectionRule(mode="percent", value=0.20),
            stop_loss=ProtectionRule(mode="percent", value=0.10),
        ),
    )

    plan = engine.build_plan(
        inst_id="BTC-USDT-SWAP",
        signal=signal,
        td_mode="cross",
        pos_side="long",
        latest_price=100.0,
        atr=1.0,
        trace_id="uplratio",
    )

    payload = engine._build_attach_algo_orders(plan.protection)

    assert payload == [
        {
            "tpTriggerPx": "102",
            "tpTriggerPxType": "last",
            "tpOrdPx": "-1",
            "tpOrdKind": "condition",
            "slTriggerPx": "99",
            "slTriggerPxType": "last",
            "slOrdPx": "-1",
            "slOrdKind": "condition",
        }
    ]
```

```python
# tests/test_protection_order_manager.py
def test_enforce_places_single_oco_from_live_position_leverage() -> None:
    client = _DummyOKX(
        positions=[{
            "instId": "PUMP-USDT-SWAP",
            "posSide": "net",
            "pos": "1",
            "avgPx": "0.001917",
            "lever": "10",
            "mgnMode": "isolated",
        }]
    )
    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.20, stop_loss_upl_ratio=0.10),
    )

    manager.enforce()

    assert client.placed[0]["tp_trigger_px"] == "0.00195534"
    assert client.placed[0]["sl_trigger_px"] == "0.00189783"
```

- [ ] **Step 2: Run the protection tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_execution_clordid.py tests/test_protection_order_manager.py
```

Expected:

```text
FAIL ... tpTriggerPx
FAIL ... slTriggerPx
```

- [ ] **Step 3: Implement leverage-aware conversion in execution and protection sync**

```python
# core/engine/execution.py
def _upl_ratio_to_trigger_px(
    self,
    *,
    entry_price: float,
    leverage: float,
    action: SignalAction,
    target_kind: str,
    upl_ratio: float,
) -> Optional[float]:
    lev = max(1.0, float(leverage or 1.0))
    move_ratio = abs(float(upl_ratio or 0.0)) / lev
    if target_kind == "tp":
        direction = 1 if action == SignalAction.BUY else -1
    else:
        direction = -1 if action == SignalAction.BUY else 1
    return entry_price * (1 + direction * move_ratio)
```

```python
# core/engine/trading.py
execution_plan = self.execution_engine.build_plan(
    inst_id=inst_id,
    signal=signal,
    td_mode=td_mode,
    pos_side=pos_side,
    latest_price=float(latest_row.get("close", 0.0) or 0.0),
    atr=float(latest_row.get("atr", 0.0) or 0.0),
    leverage=self.leverage,
    trace_id=trace_id,
)
```

```python
# core/engine/protection_orders.py
def _resolve_leverage(self, entry: Dict[str, Any]) -> float:
    try:
        return max(1.0, float(entry.get("lever") or 1.0))
    except (TypeError, ValueError):
        logger.warning("保护单同步杠杆解析失败 inst={} lever={}", entry.get("instId"), entry.get("lever"))
        return 1.0
```

```python
# core/engine/protection_orders.py
leverage = self._resolve_leverage(entry)
if thresholds.take_profit_upl_ratio > 0:
    move = thresholds.take_profit_upl_ratio / leverage
    factor = 1 + move if direction == "long" else 1 - move
    tp_trigger_px = self._format_price(avg_px * factor)
```

- [ ] **Step 4: Run the protection tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_execution_clordid.py tests/test_protection_order_manager.py tests/test_trading_pipeline.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit the leverage-aware protection conversion**

```bash
git add core/engine/execution.py core/engine/trading.py core/engine/protection_orders.py tests/test_execution_clordid.py tests/test_protection_order_manager.py tests/test_trading_pipeline.py
git commit -m "feat: convert runtime protection to leverage-aware upl triggers"
```

### Task 3: Validate Protection Sync Results Instead of Logging Blind Success

**Files:**
- Modify: `core/engine/protection_orders.py`
- Test: `tests/test_protection_order_manager.py`

- [ ] **Step 1: Write the failing sync-failure tests**

```python
# tests/test_protection_order_manager.py
def test_enforce_logs_failed_place_algo_order(monkeypatch) -> None:
    client = _DummyOKX(
        positions=[{
            "instId": "DOGE-USDT-SWAP",
            "posSide": "net",
            "pos": "0.01",
            "avgPx": "0.09333",
            "lever": "3",
            "mgnMode": "isolated",
        }]
    )
    client.place_algo_order = lambda **payload: {
        "error": {"code": "54000", "message": "place failed", "data": [{"sCode": "54000", "sMsg": "reject"}]}
    }
    errors = []

    class _Logger:
        def info(self, *args, **kwargs):
            return None
        def error(self, message, *args):
            errors.append((message, args))
        def warning(self, message, *args):
            errors.append((message, args))

    monkeypatch.setattr("core.engine.protection_orders.logger", _Logger())

    manager = ProtectionOrderManager(
        okx_client=client,
        thresholds=ProtectionThresholds(take_profit_upl_ratio=0.20, stop_loss_upl_ratio=0.10),
    )
    manager.enforce()

    assert any("event=protection_order_sync_failed" in msg for msg, _ in errors)
```

- [ ] **Step 2: Run the single sync-failure test to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_protection_order_manager.py::test_enforce_logs_failed_place_algo_order
```

Expected:

```text
FAIL ... event=protection_order_sync_failed
```

- [ ] **Step 3: Implement response validation helpers**

```python
# core/engine/protection_orders.py
def _assert_algo_success(self, *, operation: str, inst_id: str, payload: Dict[str, Any], response: Dict[str, Any]) -> bool:
    error = response.get("error") if isinstance(response, dict) else None
    if isinstance(error, dict):
        logger.error(
            "event=protection_order_sync_failed inst_id={} operation={} code={} msg={} payload={}",
            inst_id,
            operation,
            error.get("code") or "",
            error.get("message") or "",
            payload,
        )
        return False
    for item in response.get("data") or []:
        if str(item.get("sCode") or "0") not in {"0", ""}:
            logger.error(
                "event=protection_order_sync_failed inst_id={} operation={} code={} msg={} payload={}",
                inst_id,
                operation,
                item.get("sCode") or "",
                item.get("sMsg") or "",
                payload,
            )
            return False
    return True
```

```python
# core/engine/protection_orders.py
response = self.okx.place_algo_order(**payload)
self._assert_algo_success(operation="place", inst_id=desired.inst_id, payload=payload, response=response)
```

- [ ] **Step 4: Run the full protection-order manager test file**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_protection_order_manager.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit the protection sync validation**

```bash
git add core/engine/protection_orders.py tests/test_protection_order_manager.py
git commit -m "fix: validate protection sync responses"
```

### Task 4: Cancel Stale Pending Entry Orders and Keep the Current Cycle Blocked

**Files:**
- Modify: `core/engine/trading.py`
- Modify: `core/engine/execution.py`
- Test: `tests/test_cli_runtime_cycle.py`

- [ ] **Step 1: Write the failing stale-pending TTL tests**

```python
# tests/test_cli_runtime_cycle.py
def test_run_runtime_cycle_cancels_stale_pending_order_and_blocks_current_cycle(monkeypatch) -> None:
    runtime_execution = _load_runtime_execution()
    bundle = _make_bundle([{"inst_id": "WLFI-USDT-SWAP"}])
    cancelled = []

    def _run_once(**kwargs):
        bundle.engine.calls.append(kwargs)
        return {
            "signal": TradeSignal(action=SignalAction.BUY, confidence=0.9, reason="x", size=0.1),
            "execution": {
                "plan": ExecutionPlan(
                    inst_id="WLFI-USDT-SWAP",
                    action=SignalAction.BUY,
                    td_mode="isolated",
                    pos_side="net",
                    order_type="limit",
                    size=0.1,
                    price=None,
                    est_slippage=0.001,
                    blocked=True,
                    block_reason="已撤销超时挂单，下一轮再评估。",
                )
            },
        }

    bundle.engine.run_once = _run_once
    assert runtime_execution.run_runtime_cycle(bundle, _make_args(dry_run=False)) == 0
```

```python
# Add a focused engine test in the same file via monkeypatch
assert "已撤销超时挂单" in bundle.notifier.events[0].detail
```

- [ ] **Step 2: Run the stale-pending runtime test to verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_cli_runtime_cycle.py::test_run_runtime_cycle_cancels_stale_pending_order_and_blocks_current_cycle
```

Expected:

```text
FAIL ... 已撤销超时挂单
```

- [ ] **Step 3: Implement TTL-aware pending-order cancellation**

```python
# core/engine/trading.py
def _maybe_cancel_stale_pending_order(self, inst_id: str) -> Optional[str]:
    ttl_minutes = max(0, int(getattr(self.runtime_settings, "execution_pending_order_ttl_minutes", 0) or 0))
    if ttl_minutes <= 0:
        return None
    for entry in self.execution_engine.list_live_pending_orders(inst_id):
        if str(entry.get("reduceOnly") or "").lower() == "true":
            continue
        if float(entry.get("accFillSz") or 0.0) > 0:
            continue
        if not self.execution_engine.is_pending_order_stale(entry, ttl_minutes=ttl_minutes):
            continue
        self.okx.cancel_order(inst_id=inst_id, ord_id=entry.get("ordId"), cl_ord_id=entry.get("clOrdId"))
        return f"存在未成交委托：{inst_id} 已撤销超时挂单，下一轮再评估。"
    return None
```

```python
# core/engine/trading.py
pending_reason = self._maybe_cancel_stale_pending_order(inst_id) or (
    f"存在未成交委托：{inst_id} 当前仍有 live pending 单，跳过重复下单。"
)
```

```python
# core/engine/execution.py
def list_live_pending_orders(self, inst_id: str) -> List[Dict[str, Any]]:
    return [entry for entry in self.okx.list_pending_orders(inst_id) if str(entry.get("state") or "").lower() in {"live", "partially_filled"}]

def is_pending_order_stale(self, entry: Dict[str, Any], *, ttl_minutes: int) -> bool:
    created_ms = int(float(entry.get("cTime") or 0))
    return created_ms > 0 and (time.time() * 1000 - created_ms) >= ttl_minutes * 60 * 1000
```

- [ ] **Step 4: Run the runtime-cycle tests to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_cli_runtime_cycle.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit stale-pending TTL handling**

```bash
git add core/engine/trading.py core/engine/execution.py tests/test_cli_runtime_cycle.py
git commit -m "feat: cancel stale pending entry orders after ttl"
```

### Task 5: Update Runtime Docs, Env Defaults, and Verify the Whole Slice

**Files:**
- Modify: `README.md`
- Modify: `.env`
- Modify: `config/settings.py`
- Modify: `tests/test_settings_validation.py`
- Modify: `tests/test_execution_clordid.py`
- Modify: `tests/test_protection_order_manager.py`
- Modify: `tests/test_cli_runtime_workflows.py`
- Modify: `tests/test_cli_runtime_cycle.py`

- [ ] **Step 1: Write the failing doc/default-value assertions**

```python
# tests/test_settings_validation.py
def test_strategy_settings_use_upl_ratio_defaults() -> None:
    settings = StrategySettings()

    assert settings.default_take_profit_upl_ratio == 0.20
    assert settings.default_stop_loss_upl_ratio == 0.10
```

- [ ] **Step 2: Run the full targeted slice before doc changes**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_settings_validation.py tests/test_execution_clordid.py tests/test_protection_order_manager.py tests/test_cli_runtime_workflows.py tests/test_cli_runtime_cycle.py
```

Expected:

```text
PASS after Tasks 1-4, or reveal any remaining semantic mismatch before touching docs.
```

- [ ] **Step 3: Update docs and defaults**

```ini
# .env
DEFAULT_TAKE_PROFIT_UPL_RATIO=0.20
DEFAULT_STOP_LOSS_UPL_RATIO=0.10
EXECUTION_PENDING_ORDER_TTL_MINUTES=60
```

```md
# README.md
- Runtime TP/SL defaults now follow OKX position return (`uplRatio`) semantics.
- `DEFAULT_TAKE_PROFIT_UPL_RATIO=0.20` means close at +20% position return.
- `DEFAULT_STOP_LOSS_UPL_RATIO=0.10` means close at -10% position return.
- The bot converts those ratios into exchange trigger prices using leverage.
```

- [ ] **Step 4: Run fresh verification on the full targeted slice and the full suite**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_settings_validation.py tests/test_execution_clordid.py tests/test_protection_order_manager.py tests/test_cli_runtime_workflows.py tests/test_cli_runtime_cycle.py
```

Expected:

```text
... passed
```

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit docs/defaults and capture final verification**

```bash
git add .env README.md config/settings.py tests/test_settings_validation.py tests/test_execution_clordid.py tests/test_protection_order_manager.py tests/test_cli_runtime_workflows.py tests/test_cli_runtime_cycle.py
git commit -m "feat: switch runtime protection to upl ratio semantics"
```
