# NEXT_STEP

> 用途：保证“下一步只有一个目标”，降低上下文和执行漂移。

## 元信息
- 最后更新时间：2026-04-12
- 负责人：Codex

## 下一步唯一目标
- 四阶段策略/分析质量提升已完成，watchlist 也已收口为手动模式。下一步回到“交付后观测期”：持续使用 `./okx once --dry-run` / `./okx run` 观察 heartbeat、决策日志、intel 输出与 backtest 结果，只在真实运行暴露问题时做参数微调或小范围修正，不再继续扩大结构重构面。

## 执行范围（预期会改）
- `logs/`
- `data/runtime_heartbeat.json`
- `data/backtests/*.json`
- 必要时少量调整 `watchlist.json`、`.env` 和阈值配置
- `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`

## 执行约束
- 重构优先：遇到与目标方向冲突的旧实现，不新增兼容分支或兜底逻辑；调用方与测试同步到新契约。

## 完成判据（验收）
1. `intel` 输出更少误匹配、更少泛币圈噪声。
2. 决策日志可看到结构化 market/intel/strategy/llm 输出。
3. 参数调整后全量测试保持通过。
4. 不回退 `MarketAnalysis v2`、`MarketIntelSnapshot v2`、strategy structured integration、LLM structured context。
5. 三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
