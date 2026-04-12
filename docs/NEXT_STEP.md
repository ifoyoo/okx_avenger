# NEXT_STEP

> 用途：保证“下一步只有一个目标”，降低上下文和执行漂移。

## 元信息
- 最后更新时间：2026-04-12
- 负责人：Codex

## 下一步唯一目标
- 当前结构重构已基本收口，下一步进入“保护策略 + 通知观测期”：持续使用 `./okx once --dry-run` / `./okx run` 与 `./okx backtest` 观察同一套 TP/SL 规则在信号说明、attach-algo、回测退出理由上的一致性，并在真实运行中核对 Telegram 是否只在异常/阻断/下单结果上触发，不再对死配置或悬空通知逻辑投入精力。

## 执行范围（预期会改）
- `logs/`
- `data/runtime_heartbeat.json`
- `data/backtests/*.json`
- 必要时少量调整 `watchlist.json`、`.env` 和阈值配置
- `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`

## 执行约束
- 重构优先：遇到与目标方向冲突的旧实现，不新增兼容分支或兜底逻辑；调用方与测试同步到新契约。

## 完成判据（验收）
1. 同一套 `protection` 配置在策略说明、执行 attach-algo、回测退出结果上保持一致。
2. `rr` / `percent` / `atr` / `price` 的实盘或 dry-run 观测没有明显语义漂移。
3. 参数调整后全量测试保持通过。
4. 不回退已完成的 `MarketAnalysis v2`、`MarketIntelSnapshot v2`、strategy structured integration、LLM structured context、TP/SL unified contract。
5. 三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
