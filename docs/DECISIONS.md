# DECISIONS

> 用途：记录关键决策，避免新线程重复讨论。

## 决策日志（最新在上）

### 2026-04-10 - D0011 - N2 收口为 `cli.py` 单入口并删除 `main.py`
- 背景：`cli.py` 已具备完整 runtime/heartbeat/命令分发能力，但仓库仍保留 `main.py` 的 Rich 启动界面、确认交互和独立调度，导致入口重复。
- 决策：
  - 删除 `main.py` 旧入口，不保留转发 shim。
  - 保留 `okx -> cli.py` 作为唯一启动链路。
  - 删除 Rich 启动界面、`y` 确认、独立 `schedule` 调度和重复展示逻辑。
  - 本轮只同步内部架构与交接文档，不改 `README.md`。
- 原因：直接消除重复入口比保留兼容壳更清晰，能避免运行行为漂移，并符合“与目标方向冲突的旧实现不保留兜底分支”的执行约束。
- 影响：项目启动入口收敛为 `./okx ...` 或 `python cli.py ...`；`python main.py` 不再受支持；N2 文档和交接状态改为 cli-only 语义。
- 回滚方案：如后续必须兼容旧习惯，可在单独变更中新增极薄 `main.py` 提示或转发层，但不恢复旧 Rich/schedule 实现。

### 2026-04-10 - D0010 - 完成剩余节点收尾并统一“全链路可观测 + 无兜底分支”策略
- 背景：N7 之后仍有 N1/N2/N3/N5/N6/N9/N13/N14 及部分历史待办未闭环，需要一次性收尾到“全节点完成”。
- 决策：
  - N1：配置层增加强校验与 `dump_config_snapshot` 快照输出。
  - N2：CLI 调度落地 runtime heartbeat（running/idle/error/stopped）并在 `status` 展示。
  - N3：自动选币增加 spread/24h 波动/24h 成交额联合过滤 + 同基币暴露上限。
  - N5：特征层增加最小样本闸门与 `FEATURE_INDICATOR_OVERRIDES`（default/timeframe/inst@timeframe）参数分层。
  - N6：市场分析增加真实支撑阻力识别与结构化输出。
  - N9：融合层增加插件冲突仲裁器，输出 `[arb]` 结构化解释标签并记录日志事件。
  - N13：持仓保护支持 per-inst 阈值覆盖并统一输出 `event=protection_triggered`。
  - N14：回测增加点差+滑点成本模型；`backtest tune` 改为多标的聚合并输出 regime bucket 评分。
  - 同步补齐历史待办：REST 重试退避+错误分类、LLM 输出质量评分拒绝、执行 pending 超时与持仓对账、pipeline 每步耗时与失败率指标。
- 原因：在不引入兼容兜底分支的前提下，统一闭环稳定性、决策质量和可观测性，降低后续维护分叉。
- 影响：`docs/NODES.md` 待办全部打勾；全量测试提升至 `92 passed`；下一步从“节点建设”转入“实盘观测与参数迭代”。
- 回滚方案：通过配置降级（如关闭 event gate、关闭 execution reconcile、放宽阈值），不回退到旧分支路径。

### 2026-04-10 - D0009 - N7 情报标签闸门落地并确立“重构不兜底”原则
- 背景：N7 要求提升新闻源质量、输出事件标签并接入交易闸门；且本轮明确要求不为旧方向保留兼容兜底路径。
- 决策：
  - 在 `core/analysis/intel.py` 增加来源白名单/黑名单、`title+source+time-window` 去重、`regulation/security/macro` 事件标签与风险权重输出（`event_tags/event_risk_score`）。
  - 在 `RiskManager` 引入情报事件闸门（`off/degrade/block`），并将触发信息写入 `notes/reason` 及结构化日志 `event=intel_gate_applied`。
  - 在 `TradingEngine` 风控步骤透传 `market_intel` 到 `RiskManager.evaluate`，由风控统一收口闸门判断。
  - 从本轮起，对与当前重构方向冲突的旧路径不新增兼容分支或兜底逻辑，测试与调用方按新契约同步调整。
- 原因：把情报质量、事件风险、执行闸门三者打通，且通过“无兜底收口”减少分叉行为与后续维护成本。
- 影响：新增 `EVENT_GATE_*` / `NEWS_SOURCE_*` / `NEWS_DEDUPE_WINDOW_MINUTES` 等配置；`market_intel` 结构增强；相关测试按新契约更新。
- 回滚方案：若策略过严，可先调高 `EVENT_GATE_*_THRESHOLD` 或设 `EVENT_GATE_MODE=off`，不恢复旧兼容分支。

### 2026-04-10 - D0008 - N8 在融合层实施 LLM 影响上限
- 背景：需要保证 LLM 只做“增量修正”，避免直接接管方向决策。
- 决策：在 `SignalFusionEngine` 增加 `LLMInfluenceGuard`：默认禁止 BUY/SELL 反转、禁止 HOLD 提升为方向、限制置信度增幅；由 `Strategy.generate_signal(..., llm_influence_enabled=...)` 按是否启用 LLM 决定是否生效。
- 原因：在融合点统一收口，最小改动即可覆盖所有策略路径并保留可观测解释。
- 影响：新增 `LLM_INFLUENCE_*` 配置；触发上限时会在融合备注中追加“LLM 影响上限...”说明。
- 回滚方案：将 `llm_influence_enabled` 关闭或把 `LLM_INFLUENCE_ALLOW_REVERSE=true`/放宽 delta 可逐步回退限制。

### 2026-04-10 - D0007 - N4 数据新鲜度闸门放在执行前最后一跳
- 背景：需要确保使用过期行情不会触发实际下单。
- 决策：在 `TradingEngine._run_execution_step` 中对 `features` 末根 `ts` 做新鲜度校验，过期则直接阻断 `ExecutionPlan` 并写明 `block_reason`。
- 原因：该位置最靠近下单，既能拦截所有策略路径，又避免影响分析/日志链路。
- 影响：新增 `DATA_STALENESS_SECONDS` 配置；`event=data_stale_blocked` 日志用于观测。
- 回滚方案：将 `DATA_STALENESS_SECONDS` 设为 0 可关闭该闸门。

### 2026-04-09 - D0006 - N10 熔断采用 RiskManager 内建状态机 + 落盘恢复
- 背景：需要实现“日内亏损停机 + 连续亏损熔断”且重启后可恢复状态。
- 决策：在 `core/engine/risk.py` 内新增 `CircuitBreakerState`，RiskManager 读取 `daily_stats/perf_stats` 决定触发并写入 `RISK_STATE_PATH`。
- 原因：将熔断逻辑与风险评估放在同层，避免分散到 CLI/调度层导致状态漂移。
- 影响：`RiskManager.evaluate` 新增 `daily_stats/perf_stats` 入参；`TradingEngine` 风控步骤同步透传；`PerformanceTracker` 输出 `consecutive_losses`。
- 回滚方案：若触发策略过严，可先将阈值设为 0 关闭熔断，保留代码不生效。

### 2026-04-09 - D0005 - N11 采用 ExecutionPlan 持有 clOrdId 实现幂等
- 背景：N11 要求下单链路强制 `clOrdId` 并保证重试可复用。
- 决策：在 `ExecutionPlan` 新增 `cl_ord_id` 字段；`build_plan` 生成，`execute` 透传；缺失时兜底生成，避免空 `clOrdId` 下单。
- 原因：把幂等标识绑定到执行计划对象，可天然支持同 plan 重试复用同一 id。
- 影响：`core/client/rest.py` 不再发送空 `clOrdId`；保护平仓路径也显式携带 `clOrdId`。
- 回滚方案：若与上游网关规则冲突，可临时关闭 `trace_id` 拼接，仅保留随机短 id。

### 2026-04-09 - D0004 - N15 采用 trace_id + 结构化事件日志
- 背景：N12 拆分后需要提升运行链路可观测性与跨步骤追踪能力。
- 决策：在 `TradingEngine.run_once` 为每轮执行生成 `trace_id`，并在 data/analysis/signal/risk/execution 主链路输出结构化事件日志，统一包含 `action/blocked/error_code`。
- 原因：便于快速定位单轮执行状态与失败位置，支持新线程低成本复盘。
- 影响：`run_once` 返回体新增 `trace_id`；`decisions.jsonl` 记录可选 `trace_id` 字段。
- 回滚方案：若调用方不需要该字段，可忽略 `trace_id`（不影响既有键）；必要时可移除返回中的 `trace_id`。

### 2026-04-09 - D0003 - N12 采用五步 pipeline 落地
- 背景：已确认 N12 重构目标为“数据→分析→策略→风控→执行”。
- 决策：在 `core/engine/trading.py` 内部引入 step bundle + 五步执行链，`run_once` 仅负责编排。
- 原因：把策略生成与风控评估彻底解耦，降低 `run_once` 与单类职责过载。
- 影响：对外 `run_once` 返回结构保持不变；内部可测性提升，新增 `tests/test_trading_pipeline.py` 回归。
- 回滚方案：若后续出现行为偏差，可回并为旧 `_prepare_market_context/_run_strategy_pipeline/_run_execution_pipeline` 结构。

### 2026-04-09 - D0002 - 下一轮优先执行 N12 pipeline 拆分
- 背景：用户确认“下一轮继续按同样原则清理交易编排层”。
- 决策：将下一步唯一目标切换为 N12：`core/engine/trading.py` 拆分为 pipeline steps（数据→分析→策略→风控→执行）。
- 原因：降低单类过载，提升可观测性、可测试性与后续重试能力。
- 影响：`N11 clOrdId` 暂不作为下一轮首要目标，后续按批次再推进。
- 回滚方案：若拆分收益不明显，可保留外部接口不变并回并内部步骤。

### 2026-04-09 - D0001 - 建立三文件交接机制
- 背景：长会话推进 `NODES.md` 时易触发上下文超限。
- 决策：固定维护 `SESSION_STATE / DECISIONS / NEXT_STEP` 三个文件。
- 原因：把会话记忆落盘，减少对历史聊天依赖。
- 影响：新线程可直接读取文件恢复，不必回放旧对话。
- 回滚方案：删除三文件机制，恢复纯对话推进（不推荐）。
