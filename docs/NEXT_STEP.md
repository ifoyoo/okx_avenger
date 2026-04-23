# NEXT_STEP

> 用途：保证“下一步只有一个目标”，降低上下文和执行漂移。

## 元信息
- 最后更新时间：2026-04-16
- 负责人：Codex

## 下一步唯一目标
- 当前代码已将默认策略覆盖为激进版；下一步唯一目标切到“先做 dry-run smoke，再观察是否恢复真实下单”：先在默认 `BTC/ETH/SOL/XRP/DOGE/SUI` 池上跑 `./okx config-check`、`./okx status`、`./okx once --dry-run`、`./okx run --dry-run`，确认 `entry=template-qualified/fast-path` 与 `signal_candle_source=previous_confirmed/latest_confirmed` 符合预期，然后再决定是否恢复真实下单。

## 执行范围（预期会改）
- `logs/`
- `data/runtime_heartbeat.json`
- `data/backtests/*.json`
- 必要时少量调整 `watchlist.json`、`.env`、`constraints.txt` 和阈值配置
- `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`

## 执行约束
- 重构优先：遇到与目标方向冲突的旧实现，不新增兼容分支或兜底逻辑；调用方与测试同步到新契约。

## 完成判据（验收）
1. `./okx config-check` 通过，且没有新增未知 `.env` 键。
2. `./okx once --dry-run` / `./okx run --dry-run` 的 `cycle start / inst result / cycle summary` 输出能清楚区分 `entry=template-qualified` 与 `entry=fast-path`。
3. `signal_candle_source` 在决策日志里准确反映 `latest_confirmed` 或 `previous_confirmed`。
4. Telegram 只在异常/阻断/下单失败上触发，不再播报成功下单，也不再出现悬空通知。
5. 同一套 `protection` 配置在策略说明、执行 attach-algo、回测退出结果上保持一致。
6. `config-check` / `status` / backtest report 的 summary-first 输出没有出现信息丢失或误导。
7. 如有参数调整，全量测试仍保持通过，三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
