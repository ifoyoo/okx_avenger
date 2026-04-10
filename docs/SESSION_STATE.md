# SESSION_STATE

> 用途：记录“当前做到哪一步”，供新线程快速恢复。

## 元信息
- 最后更新时间：2026-04-10
- 当前主线：按 `docs/NODES.md` 推进
- 当前批次：N2 入口收口 / CLI 单入口
- 当前节点：已删除 `main.py` 旧入口，当前回到 cli-only 运行与观测准备

## 节点进度（简表）
| 节点 | 状态 | 备注 |
|---|---|---|
| N12 | 已完成 | `TradingEngine.run_once` 已拆为 data/analysis/strategy/risk/execution 五步，并新增测试覆盖 |
| N15 | 已完成 | 已引入 `trace_id` 并在主链路输出结构化日志字段（action/blocked/error_code） |
| N11 | 已完成 | `ExecutionPlan` 增加 `cl_ord_id`，下单链路默认生成并透传，执行重试可复用 |
| N10 | 已完成 | RiskManager 增加日内亏损熔断 + 连续亏损熔断 + 状态持久化恢复 |
| N4 | 已完成 | `TradingEngine` 增加数据新鲜度闸门，过期 K 线直接阻断执行并写明原因 |
| N8 | 已完成 | LLM 融合新增影响上限：禁反转、禁 HOLD 提升（默认）、限制置信度增幅 |
| N7 | 已完成 | 情报层支持源白/黑名单、窗口去重、事件标签权重，并接入风险闸门（降级/阻断） |
| N9 | 已完成 | 融合层新增插件冲突仲裁（同向增强/反向抑制/强冲突 HOLD）与 `[arb]` 解释标签 |
| N1-N3, N5-N6, N13-N14 | 已完成 | 配置强校验+快照、heartbeat、联合筛选、特征分层、支撑阻力、per-inst 保护、多标的调参与成本模型已落地 |

状态约定：`未开始` / `进行中` / `已完成` / `阻塞`

## 最近完成项（最新一条放最上）
- 时间：2026-04-10
- 节点：N2 follow-up / CLI 单入口
- 目标：删除重复入口，去掉启动界面与确认交互，把 Python 侧运行入口收口到 `cli.py`
- 结果：完成。`main.py` 已删除，Rich 启动画面、`y` 确认、独立 `schedule` 调度与重复展示逻辑一并移除；`okx` 继续只作为 shell 包装转到 `cli.py`；新增 `tests/test_cli_entrypoints.py` 锁定 `cli.main(...)` 分发、`okx -> cli.py` 目标以及 `main.py` 缺失约束。
- 变更文件：
  - `main.py`
  - `tests/test_cli_entrypoints.py`
  - `docs/NODES.md`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_cli_entrypoints.py tests/test_cli_parser.py tests/test_cli_runtime_heartbeat.py tests/test_cli_backtest_tune_utils.py` -> `16 passed`
  - `.venv/bin/python cli.py --help` -> `exit 0`
  - `./okx --help` -> `exit 0`
- 产物/日志：
  - 启动入口收口为 `./okx ...` / `python cli.py ...`
  - `main.py` 不再作为受支持入口

- 时间：2026-04-10
- 节点：运行前整理 / 新闻聚合 / watchlist 简化
- 目标：把新闻源、周期、watchlist 配置收敛到“够用且简单”，并确认当前舆情输出到底是什么。
- 结果：完成。新闻层从单一 `NewsAPI` 升级为 `CoinGecko + NewsAPI` 聚合，支持 `NEWS_PROVIDERS=coingecko,newsapi`、`COINGECKO_API_BASE`、`COINGECKO_API_KEY`、`NEWS_COIN_IDS`，并支持 watchlist 级别 `news_query/news_coin_id/news_aliases`；但实测 CoinGecko Demo `/news` 返回的是泛币圈新闻，因此新增基于别名的相关性过滤，只有标题/摘要/正文/URL 命中资产别名才算该标的新闻。当前三个位点已确认 CoinGecko coin id：`2Z -> doublezero`、`OL -> open-loot`、`JELLYJELLY -> jelly-my-jelly`。过滤后真实结果是 `2Z-USDT-SWAP`、`OL-USDT-SWAP`、`JELLYJELLY-USDT-SWAP` 目前都输出 `SNAPSHOT none`，即“系统能拉到新闻源，但暂时没有可判定为该资产专属的有效舆情”。同时，watchlist 默认配置已简化为字符串列表，默认周期收敛为 `5m + 1H`，不再要求每个品种写大量参数。另已确认 `.env` 中存在一组未被当前配置层读取的遗留 LLM 参数，但本轮先不清理，只记录状态。
- 变更文件：
  - `core/analysis/intel.py`
  - `core/data/watchlist_loader.py`
  - `core/data/auto_watchlist.py`
  - `core/engine/trading.py`
  - `config/settings.py`
  - `cli.py`
  - `watchlist.json`
  - `.env`
  - `README.md`
  - `tests/test_intel.py`
  - `tests/test_watchlist_loader.py`
  - `tests/test_trading_pipeline.py`
  - `tests/test_auto_watchlist_filters.py`
  - `tests/test_cli_parser.py`
  - `tests/test_settings_validation.py`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_intel.py tests/test_watchlist_loader.py tests/test_trading_pipeline.py tests/test_settings_validation.py` -> `passed`
  - `.venv/bin/python -m pytest -q tests/test_watchlist_loader.py tests/test_trading_pipeline.py tests/test_auto_watchlist_filters.py tests/test_cli_parser.py tests/test_settings_validation.py` -> `20 passed`
  - `.venv/bin/python -m pytest -q tests/test_intel.py tests/test_watchlist_loader.py tests/test_trading_pipeline.py tests/test_settings_validation.py tests/test_auto_watchlist_filters.py tests/test_cli_parser.py` -> `18 passed`
- 产物/日志：
  - 新增聚合配置：`NEWS_PROVIDERS`、`COINGECKO_API_BASE`、`COINGECKO_API_KEY`、`NEWS_COIN_IDS`
  - watchlist 默认简化：`["2Z-USDT-SWAP", "OL-USDT-SWAP", "JELLYJELLY-USDT-SWAP"]`
  - 默认周期简化：基础周期 `5m`，高周期 `1H`
  - 当前实盘语义：三个位点的新闻快照均为 `none`，不是报错，而是“暂无高相关资产新闻”

- 时间：2026-04-10
- 节点：N1-N3 / N5-N6 / N9 / N13-N14（收尾批）
- 目标：完成剩余节点改造并关闭 `NODES` 未完成项。
- 结果：完成。新增配置强校验与配置快照、CLI runtime heartbeat、自动选币联合质量过滤与同币种暴露上限、特征最小样本与 timeframe/inst 参数分层、支撑阻力识别与文本输出、策略冲突仲裁、保护层 per-inst 阈值与结构化触发日志、回测成本模型（滑点+点差）及多标的分桶调参；同时补齐 REST 重试退避/错误分类、LLM 输出质量评分拒绝、执行 pending 超时与持仓对账、pipeline 每步耗时与失败率指标。
- 变更文件：
  - `config/settings.py`
  - `config/__init__.py`
  - `core/client/rest.py`
  - `core/data/auto_watchlist.py`
  - `core/data/features.py`
  - `core/analysis/market.py`
  - `core/analysis/llm_brain.py`
  - `core/strategy/fusion.py`
  - `core/strategy/core.py`
  - `core/engine/execution.py`
  - `core/engine/protection.py`
  - `core/engine/trading.py`
  - `core/backtest/simple.py`
  - `cli.py`
  - `main.py`
  - `tests/test_settings_validation.py`
  - `tests/test_cli_runtime_heartbeat.py`
  - `tests/test_auto_watchlist_filters.py`
  - `tests/test_feature_overrides.py`
  - `tests/test_protection_monitor_thresholds.py`
  - `tests/test_rest_retry.py`
  - `tests/test_strategy_fusion_guard.py`
  - `tests/test_strategy_core.py`
  - `tests/test_execution_clordid.py`
  - `tests/test_backtest_simple.py`
  - `tests/test_llm_brain.py`
  - `tests/test_market_analyzer.py`
  - `tests/test_cli_backtest_tune_utils.py`
  - `docs/NODES.md`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q` -> `92 passed`
- 产物/日志：
  - 配置快照文件：`data/config_snapshot.json`
  - 运行心跳文件：`data/runtime_heartbeat.json`
  - 新增日志事件：`event=okx_retry`、`event=strategy_conflict_arbiter`、`event=protection_triggered`、`event=run_once_failed`

- 时间：2026-04-10
- 节点：N7
- 目标：增强情报源质量、输出事件标签风险权重，并联动交易闸门。
- 结果：完成。`intel` 增加来源白名单/黑名单与 `title+source+time-window` 去重；输出 `regulation/security/macro` 标签与权重（`event_tags/event_risk_score`）；`RiskManager` 新增 `off/degrade/block` 情报闸门并在 reason/log 中可观测；执行原则明确为“重构不做兼容兜底”。
- 变更文件：
  - `core/analysis/intel.py`
  - `core/engine/risk.py`
  - `core/engine/trading.py`
  - `config/settings.py`
  - `tests/test_intel.py`
  - `tests/test_risk_circuit_breaker.py`
  - `tests/test_trading_pipeline.py`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_intel.py tests/test_risk_circuit_breaker.py tests/test_trading_pipeline.py` -> `13 passed`
  - `.venv/bin/python -m pytest -q` -> `69 passed`
- 产物/日志：
  - 新增配置：`NEWS_SOURCE_WHITELIST`、`NEWS_SOURCE_BLACKLIST`、`NEWS_DEDUPE_WINDOW_MINUTES`、`EVENT_TAG_ENABLED`、`EVENT_GATE_MODE`、`EVENT_GATE_*`
  - 新增情报字段：`event_tags`、`event_risk_score`
  - 新增风控日志事件：`event=intel_gate_applied`

- 时间：2026-04-10
- 节点：N8
- 目标：为 LLM 结果增加影响上限（仅调置信度/仓位，不允许直接反转）。
- 结果：完成。融合层新增 LLM guard：禁止 BUY/SELL 直接反转、可配置禁止 HOLD→方向、限制置信度增幅，并输出“LLM 影响上限”解释。
- 变更文件：
  - `core/strategy/fusion.py`
  - `core/strategy/core.py`
  - `core/engine/trading.py`
  - `config/settings.py`
  - `tests/test_strategy_fusion_guard.py`
  - `tests/test_trading_pipeline.py`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
  - `docs/NODES.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_strategy_fusion_guard.py tests/test_strategy_core.py tests/test_trading_pipeline.py` -> `10 passed`
  - `.venv/bin/python -m pytest -q` -> `65 passed`
- 产物/日志：
  - 新增配置：`LLM_INFLUENCE_MAX_CONF_DELTA`、`LLM_INFLUENCE_ALLOW_REVERSE`、`LLM_INFLUENCE_ALLOW_HOLD_TO_DIRECTION`
  - 融合备注中可见：`LLM 影响上限...`

- 时间：2026-04-10
- 节点：N4
- 目标：增加数据新鲜度闸门（过期跳过下单）。
- 结果：完成。执行层新增 `features.ts` 新鲜度检查，超过阈值直接 `plan.blocked=true` 并写入 `block_reason`。
- 变更文件：
  - `core/engine/trading.py`
  - `config/settings.py`
  - `tests/test_trading_pipeline.py`
  - `docs/NODES.md`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_trading_pipeline.py tests/test_risk_circuit_breaker.py tests/test_execution_clordid.py` -> `10 passed`
  - `.venv/bin/python -m pytest -q` -> `62 passed`
- 产物/日志：
  - 新增配置：`DATA_STALENESS_SECONDS`
  - 新增阻断日志事件：`event=data_stale_blocked`

- 时间：2026-04-09
- 节点：N10
- 目标：新增硬风控熔断（日内亏损 + 连续亏损）并支持状态持久化恢复。
- 结果：完成。`RiskManager` 增加 `CircuitBreakerState` 落盘；`evaluate` 接入 `daily_stats/perf_stats`；触发后强制 HOLD 并阻断新仓。
- 变更文件：
  - `core/engine/risk.py`
  - `core/engine/trading.py`
  - `config/settings.py`
  - `core/data/performance.py`
  - `tests/test_risk_circuit_breaker.py`
  - `tests/test_performance_tracker.py`
  - `tests/test_trading_pipeline.py`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_risk_circuit_breaker.py tests/test_performance_tracker.py tests/test_trading_pipeline.py` -> `6 passed`
  - `.venv/bin/python -m pytest -q` -> `60 passed`
- 产物/日志：
  - 熔断状态文件默认：`data/risk_circuit_state.json`
  - 新增配置：`RISK_DAILY_LOSS_LIMIT*`、`RISK_CONSECUTIVE_LOSS_LIMIT`、`RISK_STATE_PATH`

- 时间：2026-04-09
- 节点：N11
- 目标：下单链路强制 `clOrdId` 幂等（生成、透传、复用）。
- 结果：完成。`ExecutionPlan` 新增 `cl_ord_id`；`build_plan` 按 `inst/action/trace_id` 生成；`execute` 强制透传至 `OKXClient.place_order`。
- 变更文件：
  - `core/engine/execution.py`
  - `core/engine/trading.py`
  - `core/client/rest.py`
  - `core/engine/protection.py`
  - `tests/test_execution_clordid.py`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_execution_clordid.py tests/test_trading_pipeline.py` -> `6 passed`
  - `.venv/bin/python -m pytest -q` -> `57 passed`
- 产物/日志：
  - `ExecutionPlan.cl_ord_id`
  - clOrdId 生成规则：`cx + action + inst + trace + nonce`（截断至 32）

- 时间：2026-04-09
- 节点：N15
- 目标：引入 trace_id 并统一主链路结构化日志，提升可观测性。
- 结果：完成。`run_once` 生成 `trace_id`，贯穿 data/analysis/signal/risk/execution/run_once_done；并为执行结果统一输出 `action/blocked/error_code`。
- 变更文件：
  - `core/engine/trading.py`
  - `core/analysis/logger.py`
  - `tests/test_trading_pipeline.py`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_trading_pipeline.py` -> `3 passed`
  - `.venv/bin/python -m pytest -q` -> `54 passed`
- 产物/日志：
  - `run_once` 返回新增 `trace_id`
  - pipeline 结构化日志事件：`run_once_start/data_done/analysis_done/signal_done/risk_done/execution_done/run_once_done`

- 时间：2026-04-09
- 节点：N12
- 目标：交易编排层拆 pipeline step（数据→分析→策略→风控→执行），降低单类过载。
- 结果：完成。`run_once` 改为五步串联；策略与风控职责拆开；执行步骤保持原行为。
- 变更文件：
  - `core/engine/trading.py`
  - `tests/test_trading_pipeline.py`
  - `docs/SESSION_STATE.md`
  - `docs/DECISIONS.md`
  - `docs/NEXT_STEP.md`
- 验证命令与结果：
  - `.venv/bin/python -m pytest -q tests/test_trading_pipeline.py` -> `2 passed`
  - `.venv/bin/python -m pytest -q` -> `53 passed`
- 产物/日志：
  - 新增 pipeline 回归测试：`tests/test_trading_pipeline.py`

## 当前阻塞
- 无明确阻塞。
- 已知现实约束：免费新闻源对小币种命中率很低，CoinGecko Demo `/news` 更偏泛币圈资讯，因此当前“无有效专属舆情”属于数据现实，不是实现故障。
- 已知待清理但未执行：`.env` 中遗留未使用参数 `ENABLE_LLM_ANALYSIS`、`LLM_WEIGHT`、`AI_PROVIDER`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`。

## 给新线程的最小上下文
- 先读：`docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`
- 然后：默认假设当前 watchlist 只保留字符串简写，默认周期是 `5m + 1H`，新闻源是 `CoinGecko + NewsAPI`
- 再然后：按 `docs/NEXT_STEP.md` 的“下一步唯一目标”直接执行
