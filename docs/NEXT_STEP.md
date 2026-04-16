# NEXT_STEP

> 用途：保证“下一步只有一个目标”，降低上下文和执行漂移。

## 元信息
- 最后更新时间：2026-04-16
- 负责人：Codex

## 下一步唯一目标
- 当前代码已补齐 live pending 对账与重复下单闸门；下一步唯一目标切到“清理账户残留委托并做上线 smoke”：先确认并处理历史 live pending 普通委托（当前已知 `PUMP-USDT-SWAP` 有残留），然后在只保留 `BTC-USDT-SWAP` 的前提下依次执行 `./okx config-check --api-check`、`./okx once --dry-run`、`./okx run --dry-run`，确认配置、输出、通知、TP/SL 说明、LLM 输出与 runtime 退出码一致后，再决定是否恢复真实下单。

## 执行范围（预期会改）
- 交易所账户中的历史普通委托状态
- `logs/`
- `data/runtime_heartbeat.json`
- `data/backtests/*.json`
- 必要时少量调整 `watchlist.json`、`.env`、`constraints.txt` 和阈值配置
- `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`

## 执行约束
- 重构优先：遇到与目标方向冲突的旧实现，不新增兼容分支或兜底逻辑；调用方与测试同步到新契约。

## 完成判据（验收）
1. `./okx config-check --api-check` 通过，且没有新增未知 `.env` 键。
2. `./okx once --dry-run` / `./okx run --dry-run` 的 `cycle start / inst result / cycle summary` 输出与实际单标的行为一致。
3. 账户中不存在上一次误判遗留的 live pending 普通委托，或至少这些委托已被人工确认并与本轮运行隔离。
4. Telegram 只在异常/阻断/下单失败上触发，不再播报成功下单，也不再出现悬空通知。
5. 同一套 `protection` 配置在策略说明、执行 attach-algo、回测退出结果上保持一致。
6. `config-check` / `status` / backtest report 的 summary-first 输出没有出现信息丢失或误导。
7. 如有参数调整，全量测试仍保持通过，三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
