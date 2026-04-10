# NEXT_STEP

> 用途：保证“下一步只有一个目标”，降低上下文和执行漂移。

## 元信息
- 最后更新时间：2026-04-10
- 负责人：Codex

## 下一步唯一目标
- N2 入口收口已完成。下一步回到“cli-only 实盘观测期”：使用 `./okx run` 或 `./okx once --dry-run` 连续运行，并基于 heartbeat/决策日志做参数微调，不恢复 `main.py` 或启动 UI。

## 执行范围（预期会改）
- `logs/`、`data/config_snapshot.json`、`data/runtime_heartbeat.json`（运行观测）
- 必要时仅调整 `.env` 参数与少量阈值配置
- `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`

## 执行约束
- 重构优先：遇到与目标方向冲突的旧实现，不新增兼容分支或兜底逻辑；调用方与测试同步到新契约。

## 完成判据（验收）
1. 连续运行期间 heartbeat 持续更新且无异常中断。
2. 决策日志能观测关键事件（risk/intel/arb/execution）。
3. 参数调整后全量测试保持通过。
4. 持续使用 `cli.py` / `okx` 单入口，不恢复 `main.py` 启动路径。
5. 三文件持续同步更新。

## 新线程恢复指令（可直接复制）
请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
