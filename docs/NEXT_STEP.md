# NEXT_STEP

> 用途：保证“下一步只有一个目标”，降低上下文和执行漂移。

## 元信息
- 最后更新时间：2026-04-12
- 负责人：Codex

## 下一步唯一目标
- 当前代码收口已达到可交付状态，下一步唯一目标切到“上线 smoke / 观测期”：先用 `./okx config-check --api-check`、`./okx once --dry-run`、`./okx run --dry-run` 在只保留 `BTC-USDT-SWAP`（可选再加 `ETH-USDT-SWAP`）的前提下连续观察配置、输出、通知、TP/SL 说明、LLM 输出与 runtime 退出码是否一致，再决定是否打开真实下单。

## 执行范围（预期会改）
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
3. Telegram 只在异常/阻断/下单结果上触发，不再出现悬空通知。
4. 同一套 `protection` 配置在策略说明、执行 attach-algo、回测退出结果上保持一致。
5. `config-check` / `status` / backtest report 的 summary-first 输出没有出现信息丢失或误导。
6. 如有参数调整，全量测试仍保持通过，三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
