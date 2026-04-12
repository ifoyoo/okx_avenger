# DECISIONS

> 用途：记录关键决策，避免新线程重复讨论。

## 决策日志（最新在上）

### 2026-04-12 - D0021 - 止盈止损统一为“规则意图 + 入场价解析”单一契约
- 背景：原有 TP/SL 同时存在策略侧目标构造、执行层 attach-algo 转换和回测忽略保护的问题；`ratio` 旧写法在 watchlist 测试中出现，但主实现只认 `percent`。
- 决策：
  - `TradeSignal.protection` 改为携带 `ProtectionRule` 规则意图，而不是提前解析好的交易所目标。
  - 在 `core.protection.resolve_trade_protection()` 中统一按入场参考价和 ATR 解析为 `ResolvedTradeProtection`，供执行层和回测层共用。
  - 新增 `rr` 止盈模式，以已解析止损距离为 `1R` 计算止盈；`ratio/pct/percentage` 统一归一到 `percent`。
  - 回测开仓后同根 bar 即检查 TP/SL，若同根同时命中止盈和止损，按保守原则先记止损。
- 原因：先把“保护规则是什么”与“执行/回测如何落地”分层，才能让实盘和回测真正共享一套语义，并修掉旧别名漂移。
- 影响：README 中的保护说明改为规则驱动语义；执行 attach-algo 和回测退出理由终于对齐；默认配置面不增加新入口，只增强现有 `protection` 对象表达力。
- 回滚方案：如 `rr` 或同根 bar 保守处理不符合预期，可单独回退对应解析逻辑，但不恢复“策略直接输出交易所目标”的旧分叉。

### 2026-04-12 - D0020 - 删除未使用的 `APP_VERSION` / `APP_AUTHOR` 配置
- 背景：`.env` 中保留了带个人化命名的 `APP_VERSION` / `APP_AUTHOR`，但当前代码除配置模型外没有任何消费点。
- 决策：
  - 从 `RuntimeSettings` 删除 `APP_VERSION` / `APP_AUTHOR` 字段。
  - 从 `.env` 删除对应配置与注释。
  - 若未来需要版本方案，优先使用 Git tag / commit 派生，而不是重新引入手工 `.env` 元信息。
- 原因：无消费的配置只会污染配置面，并制造“看起来重要但实际上无效”的噪声。
- 影响：当前运行行为不变；配置面更干净；后续版本标识若需要，应走代码或发布流程而不是环境变量。
- 回滚方案：如后续确有展示需求，可基于明确使用点重新引入，但需同步消费逻辑与测试。

### 2026-04-12 - D0019 - 仓库清理以“当前实现可运行且可交付”为边界
- 背景：用户要求清理项目目录中与当前实现无关的代码、文件和文件夹，并将结果推送远端。
- 决策：
  - 删除已废弃的自动 watchlist 实现、旧 OKX 静态文档快照和本地旧 worktree。
  - README 只保留当前真实入口 `./okx` / `python cli.py`，去掉 `main.py`、Rich 启动页、确认交互等失效说明。
  - 保留当前运行必须的代码、测试、交接文档和开发环境，不把未收口的 backtest 本地改动混入本次提交。
- 原因：仓库清理的目标是提高可维护性和可读性，而不是破坏当前可运行环境；需要在“彻底”与“安全”之间收住边界。
- 影响：远端仓库将更贴近当前真实实现；本地开发残留明显减少；未纳入本次提交的 backtest 改动继续保留在本地工作区。
- 回滚方案：若后续确认某个被删除的资料文件仍需保留，应以当前实现为基准重新引入，而不是恢复整套旧路径。

### 2026-04-12 - D0018 - Watchlist 收口为纯手动模式，不再保留 auto/mixed
- 背景：交付后观测期需要稳定输入集合，自动/混合选币会让监控标的漂移；用户明确要求把自动模式清理掉。
- 决策：
  - 删除 `WATCHLIST_MODE` 与所有 `AUTO_WATCHLIST_*` 配置项。
  - `WatchlistManager` 改为只读取 `watchlist.json`，不再根据模式切换来源。
  - 删除 `core/data/auto_watchlist.py` 与对应测试，文档改为手动 watchlist 单一路径。
- 原因：观测期最重要的是可复现和可解释，固定标的集合比动态选币更容易定位问题，也更符合当前交付阶段目标。
- 影响：运行标的完全由 `watchlist.json` 决定；后续如要切换监控池，直接改文件而不是改模式或自动筛选阈值。
- 回滚方案：如未来确实需要重启动态选币，应以新需求重新设计，而不是恢复这次删除的旧实现。

### 2026-04-12 - D0017 - LLM prompt 改为显式消费 structured market/intel context
- 背景：前 3 个阶段已把市场分析和 intel 结构化，但 `LLMBrain` 仍主要依赖长文本和原始 dict dump，等于让模型重复做一次解析。
- 决策：
  - 为 `LLMBrain.analyze(...)` 增加 `structured_market_analysis` 与 `structured_market_intel` 可选参数。
  - `TradingEngine` 负责将 `analysis_result` 与 `market_intel` 压成 compact structured block 传给 `LLMBrain`。
  - 保留 `deterministic_summary` / `deterministic_analysis` 作为补充上下文，不再是唯一结构来源。
- 原因：让前面已完成的结构化 contract 真正进入 LLM 输入，提高稳定性，并减少 prompt 里“靠长文本二次解析”的损耗。
- 影响：LLM prompt 质量提升，但不改变调用方是否启用 LLM 的主开关与 guard 机制。
- 回滚方案：如兼容性出现问题，可去掉 structured 参数，仅保留旧文本字段。

### 2026-04-12 - D0016 - Strategy/Fusion 优先消费 `MarketAnalysis v2` 而不是自由文本
- 背景：`market.py` 已升级为结构化 contract，但 `Strategy.generate_signal(...)` 仍主要消费 `analysis_text`，导致确定性分析在融合层经常退化为 `HOLD + 0.5`。
- 决策：
  - `Strategy.generate_signal(...)` 增加 `market_analysis` 可选输入。
  - `AnalysisInterpreter` 增加 `from_market_analysis()`，把结构化趋势/动量/风险转为 `AnalysisView`。
  - 当 `analysis_text` 不是结构化 JSON 时，优先使用 `market_analysis` 生成的 structured view。
- 原因：前面重构出的结构化分析必须直接进入融合层，否则市场分析质量提升不会落到真实决策上。
- 影响：确定性模式下策略融合不再只依赖自由文本；LLM JSON 路径保持兼容。
- 回滚方案：如 structured view 效果不佳，可退回纯文本解释路径，但保留 `market_analysis` 入参。

### 2026-04-12 - D0015 - Intel 对所有 provider 统一 relevance scoring 与加权聚合
- 背景：原有 `intel` 只对 CoinGecko 泛新闻做 alias relevance 过滤，NewsAPI 主要依赖查询词，仍会混入弱相关或泛行业新闻。
- 决策：
  - 所有 provider 的 article 都统一经过 relevance scoring/filtering。
  - `NewsHeadline` 增加 `relevance_score` / `matched_aliases`；`MarketIntelSnapshot` 增加 `analysis_version` / `avg_relevance_score` / `provider_counts` / `matched_aliases`。
  - `sentiment_score` 与 `event_tags` 聚合改为 relevance-weighted。
- 原因：如果 intel 本身不先把“有多相关”建模，下游 `fusion` 和 `llm` 仍会吃到真假相关混杂的输入。
- 影响：宏观但不指向资产本身的新闻更容易被过滤掉；snapshot 更适合复盘与下游消费。
- 回滚方案：如过滤过严，可调低 relevance 阈值或临时回退到 query-only 过滤策略。

### 2026-04-12 - D0014 - 第 1 阶段市场分析重构采用“structured assessment first”
- 背景：用户要求后续按我的判断连续推进“市场分析 / intel / fusion / llm”四个方向，但如果一开始就同时动四块，会失去归因能力。
- 决策：
  - 先只做第 1 阶段：[`core/analysis/market.py`](/Users/t/Desktop/Python/okx/core/analysis/market.py)。
  - 在 `market.py` 内部引入 `TrendAssessment`、`MomentumAssessment`、`LevelAssessment`、`RiskAssessment` 四类结构化结果。
  - `MarketAnalysis` 保留旧字段并新增 `trend/momentum/levels/risk/analysis_version`，旧字段由新结构回填。
  - 文本分析从“独立判断层”改为 assessment 渲染层，不再允许结构结果和文本各跑一套逻辑。
- 原因：后续 `fusion` 与 `llm` 需要的是稳定、可解释的确定性输入；先把 market contract 做干净，比继续堆 prompt 或调权重更有基础价值。
- 影响：`MarketAnalysis` 兼容性保留；后续阶段可以逐步改为直接消费 assessment，而不是继续解析自由文本。
- 回滚方案：如新结构证明没有收益，可退回只保留旧字段的输出形式，但不恢复“文本和结构各自判断”的双路径。

### 2026-04-11 - D0013 - 回测结果持久化从 `backtest_helpers` 拆到独立 storage 模块
- 背景：CLI command package 拆分后，`backtest_helpers.py` 同时承担数值计算、摘要打印和回测文件读写，职责边界开始混杂。
- 决策：
  - 新增 `cli_app/backtest_storage.py`，集中放置 `BACKTEST_DIR/BACKTEST_LATEST`、`_serialize_backtest_record`、`_save_backtest_records`、`_load_backtest_records`。
  - `cli_app/backtest_workflows.py` 改为显式依赖 storage 模块，`backtest_helpers.py` 只保留回测评分、市场状态分桶、摘要打印等纯 helper 逻辑。
  - 增加 `tests/test_cli_backtest_storage.py` 锁定存储模块契约。
- 原因：把“回测结果落盘”从纯计算 helper 中剥离后，backtest workflow 的依赖关系更清晰，也更便于后续替换存储路径或格式而不污染计算逻辑。
- 影响：`backtest_helpers.py` 体积进一步缩小；回测持久化职责有独立测试保护；`report_backtest` 默认读取 `BACKTEST_LATEST` 的行为不变。
- 回滚方案：如后续证明 storage 模块拆分没有收益，可把三个存储函数与常量并回 `backtest_helpers.py`，但保留现有测试契约。

### 2026-04-11 - D0012 - N2 follow-up 采用 `cli_app/` 命令包承载 CLI 内部实现
- 背景：`main.py` 删除后，`cli.py` 仍继续累积参数定义、命令注册、workflow、状态展示与回测辅助职责，虽保持单入口但内部边界仍不稳。
- 决策：
  - 保留 `cli.py` 作为唯一真实入口文件，只暴露 `build_parser()` 与 `main()` facade。
  - 引入 `cli_app/` 包承载内部实现，并按 parser / registry / commands / workflows / reporting / helpers / storage 分层拆分。
  - 顶层命令名继续保持 `once/run/status/config-check/backtest/strategies`，不引入目录扫描式自动注册，也不恢复第二入口。
- 原因：用户契约需要稳定，但内部实现需要继续降复杂度；把 CLI 作为应用壳层而不是交易核心层的一部分，更符合仓库当前边界。
- 影响：`./okx ...` 与 `python cli.py ...` 的对外行为保持不变；CLI 代码可在更小模块内继续迭代；`cli.py` 不再承担过载实现。
- 回滚方案：若 `cli_app/` 分层被证明增加维护成本，可把部分小模块并回 workflow 层，但不恢复 `main.py` 或多入口结构。

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
