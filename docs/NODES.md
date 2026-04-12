# OKX 自动交易项目节点清单（执行链路版）

> 目标：把当前项目拆成可独立优化的节点，逐个做“输入-输出-约束-优化”。
>
> 范围：`okx run/once` 实盘链路；`backtest`/`strategies` 作为辅助链路。

---

## 0. 总览（主链路）

```text
CLI(cli.py/okx)
  -> Config(.env -> settings)
  -> Watchlist(watchlist.json)
  -> Data(REST/WS -> candles/features/snapshot)
  -> Analysis(确定性 market + 可选 intel + 可选 llm brain)
  -> Strategy(plugins + fusion + sizing + protection)
  -> RiskManager
  -> ExecutionPlan -> place_order
  -> Monitor/Log/Notify/Perf
```

`./okx strategies` 与 `./okx backtest` 视为主实盘运行链路之外的辅助 CLI 路径，分别用于观测/调优辅助与离线验证。

---

## 1. 节点明细（按执行顺序）

## N1 配置层
- **文件**：`config/settings.py`、`config/base.py`、`.env`
- **输入**：环境变量（账户、策略、运行、通知、LLM、NEWS）
- **输出**：`AppSettings`
- **当前实现**
  - 已覆盖：`Account/Strategy/Runtime/Notification/LLM/Intel`
  - `get_settings()` 带缓存（`lru_cache`）
  - 已增加配置强校验与配置快照输出，便于运行前拦截错误配置和事后复盘
- **风险点**
  - 运行期改 `.env` 仍依赖显式 `cache_clear`
  - 配置面持续增长时，需要同步维护文档、默认值和测试覆盖
- **优化待办**
  - [x] 增加强校验（权重范围、超时范围、URL合法性）
  - [x] 增加配置快照输出（用于故障复盘）

---

## N2 入口与调度层
- **文件**：`cli.py`、`okx`、`cli_app/*`
- **输入**：CLI 参数 + `AppSettings`
- **输出**：单轮执行请求/循环调度
- **当前实现**
  - `okx` 仅作为 shell 包装，统一转调 `cli.py`
  - `cli.py` 仅保留薄入口；参数解析、命令注册、workflow、reporting 已拆入 `cli_app/`
  - 顶层命令仍为 `once/run/status/config-check/strategies/backtest`
- **风险点**
  - `run` 常驻调度仍主要依赖单进程循环，现场稳定性需要靠实跑验证
  - CLI 内部已拆成多模块，后续新增功能时需继续守住 parser/workflow/reporting/storage 的边界
- **优化待办**
  - [x] 收口为 `cli.py` 单入口并删除 `main.py` 重复调度
  - [x] 增加运行健康状态文件（heartbeat）
  - [x] 将 CLI 内部实现拆为 `cli_app/` 命令包

---

## N3 标的管理（Watchlist）
- **文件**：`core/data/watchlist_loader.py`
- **输入**：`watchlist.json`
- **输出**：`[{inst_id,timeframe,higher_timeframes,max_position,protection}]`
- **当前实现**
  - 运行时只读取 `watchlist.json`
  - 字符串条目会自动补默认周期 `5m + 1H`，对象条目可覆盖周期、仓位、保护和新闻别名
- **风险点**
  - 监控池完全依赖手工维护，扩缩表需要人工更新文件
  - 小币种 `coin_id/news_aliases` 仍建议显式配置，避免误判或漏判
- **优化待办**
  - [x] 收口为纯手动 watchlist
  - [x] 保留对象覆盖能力，避免为少数特殊标的扩配置面

---

## N4 市场数据采集层（REST/WS）
- **文件**：`core/client/rest.py`、`core/client/stream.py`
- **输入**：inst/timeframe/API 凭证
- **输出**：K线、盘口、成交、资金费率、持仓量
- **当前实现**
  - REST 全封装 + `_ensure_success`，并带重试退避与错误分类统计
  - WS 缓存 candles/books/trades，支持断线重连；执行前有数据新鲜度闸门
- **风险点**
  - WS/REST 切换后的强一致性校验仍较有限
  - 多标的持续运行下的限频参数仍需实跑观测
- **优化待办**
  - [x] 增加请求重试退避与错误分类统计
  - [x] 增加数据新鲜度阈值（过期即跳过下单）

---

## N5 特征工程层
- **文件**：`core/data/features.py`
- **输入**：原始K线
- **输出**：含 RSI/EMA/MACD/ATR/BB/OBV/MFI/Stoch/KDJ/CCI/ADX/W%R/Ichimoku 的 DataFrame
- **当前实现**
  - 指标覆盖较全，带时间戳尺度兼容（ns/us/ms）
  - `bfill/ffill` 保证尾行可用，并已加入最小样本约束与分层参数覆盖
- **风险点**
  - 长窗口指标在低流动性或短样本场景仍天然偏噪声
  - `default/timeframe/inst@timeframe` 覆盖矩阵增长后需注意维护复杂度
- **优化待办**
  - [x] 引入最小样本约束（不足直接降级）
  - [x] 参数分层（按 timeframe/inst 配置）

---

## N6 市场分析层（确定性）
- **文件**：`core/analysis/market.py`
- **输入**：features + higher_features + snapshot + account/perf
- **输出**：`MarketAnalysis(text, summary, history_hint, ...)`
- **当前实现**
  - 以 trend/momentum/levels/risk assessment 为内核，再渲染分析文本
  - `MarketAnalysis` 已升级为 structured contract v2，并保留旧标量字段兼容
- **风险点**
  - `market.py` 仍是单文件，后续如 assessment 继续增长可再拆渲染层
  - 市场状态分类与阈值仍偏规则化，后续主要靠实跑日志与参数微调继续收敛
- **优化待办**
  - [x] 完成支撑阻力真实识别算法
  - [x] 文本输出模板化，便于回测解释对齐
  - [x] 升级为结构化 assessment contract

---

## N7 新闻/舆情情报层（可选）
- **文件**：`core/analysis/intel.py`
- **输入**：inst_id -> symbol/coin_id、多新闻源 API
- **输出**：`MarketIntelSnapshot(sentiment_score,event_tags,headlines,summary,analysis_version,...)`
- **当前实现**
  - `NEWS_ENABLED` 开关
  - `CoinGecko + NewsAPI` 聚合，支持来源白/黑名单、窗口去重、事件标签与风险闸门联动
  - 所有 provider 统一 relevance scoring/filtering，snapshot v2 暴露 `avg_relevance_score/provider_counts/matched_aliases`
- **风险点**
  - 情绪与事件识别仍是确定性关键词法，表达力有限
  - 小币 `coin_id/news_aliases` 仍建议显式配置，避免误匹配或过严过滤
- **优化待办**
  - [x] 来源白名单/黑名单
  - [x] 更强去重（title+source+time）
  - [x] 事件级标签（监管/安全/宏观）与闸门联动
  - [x] 多源聚合（CoinGecko + NewsAPI）
  - [x] 所有 provider 统一 relevance scoring/filtering
  - [x] relevance metadata 与 relevance-weighted 聚合

---

## N8 LLM 分析大脑层（可选）
- **文件**：`core/analysis/llm_brain.py`
- **输入**：确定性分析 + structured market/intel context + 账户风险
- **输出**：`BrainDecision`（严格 JSON）
- **当前实现**
  - OpenAI 兼容 `/chat/completions`
  - prompt 已显式消费 compact `structured_market_analysis` / `structured_market_intel`
  - 超时/异常自动回退，且带响应质量评分与拒绝策略，不阻塞交易主链
- **风险点**
  - prompt 漂移、模型稳定性与 token 成本仍需持续观测
  - LLM 仍应保持 advisory 角色，实际影响边界依赖融合层 guard 持续约束
- **优化待办**
  - [x] 接入 structured market/intel context
  - [x] 增加影响上限（仅调置信度，不直接反转）
  - [x] 增加响应质量评分与拒绝策略

---

## N9 策略信号层（插件+融合）
- **文件**：`core/strategy/core.py`、`core/strategy/plugins.py`
- **输入**：features、higher_features、analysis_text（可来自LLM）、`market_analysis`
- **输出**：`StrategyOutput(trade_signal,objective_signals,...)`
- **当前实现**
  - 插件开关与权重：`STRATEGY_SIGNALS_ENABLED/WEIGHTS`
  - 已接入策略：`volume_pressure`、`volatility_breakout`、`bull_trend`、`ma_golden_cross`、`shrink_pullback`、`volume_breakout`、`box_oscillation`、`one_yang_three_yin`
  - `Strategy.generate_signal(...)` 已可直接消费 `MarketAnalysis v2`，并在非结构化文本场景优先使用 structured view
  - `signals.py` / `fusion.py` / `positioning.py` 已形成更清晰边界，并带冲突仲裁解释标签
- **风险点**
  - `core.py` 仍承担编排职责，未来如继续扩策略可再下沉
  - 策略权重、仲裁阈值与解释语义仍需结合实盘日志微调
- **优化待办**
  - [x] 直接消费 `MarketAnalysis v2`
  - [x] 拆分 `signals.py` / `fusion.py` / `positioning.py` 边界
  - [x] 引入“策略冲突仲裁规则”与解释标签

---

## N10 风控层
- **文件**：`core/engine/risk.py`
- **输入**：`AccountState` + features + strategy_output
- **输出**：`RiskAssessment(trade_signal,blocked,notes)`
- **当前实现**
  - 账户可用资金占比、流动性、多周期冲突拦截
  - 日内亏损熔断、连续亏损熔断与状态持久化恢复已落地
- **风险点**
  - 熔断阈值和恢复条件仍需结合真实运行继续校准
- **优化待办**
  - [x] 日内亏损上限停机
  - [x] 连续亏损熔断
  - [x] 风控状态持久化与恢复

---

## N11 执行计划与下单层
- **文件**：`core/engine/execution.py`
- **输入**：`TradeSignal` + instrument meta + latest_price/atr
- **输出**：`ExecutionPlan` -> `ExecutionReport`
- **当前实现**
  - 合约换算、最小张数、滑点阈值、TP/SL attach
  - `ExecutionPlan` 已持有 `clOrdId`，并支持 pending 超时处理与持仓对账
- **风险点**
  - 部分成交、撤改单等更复杂订单生命周期仍有继续细化空间
  - 交易所侧拒单语义与重试策略仍需实盘观测
- **优化待办**
  - [x] 强制 `clOrdId` 幂等
  - [x] 增加 pending 订单超时处理
  - [x] 下单后持仓对账

---

## N12 交易编排层（单轮主控）
- **文件**：`core/engine/trading.py`
- **输入**：inst_id/timeframe + 各层数据
- **输出**：完整结果字典（analysis/signal/execution/order/intel/brain）
- **当前实现**
  - 已拆为 data / analysis / strategy / risk / execution 五步 pipeline，并带步骤耗时指标
  - 支持 LLM/News 可选增强，且会把 structured market/intel 在链路内继续向下游透传
- **风险点**
  - `TradingEngine` 仍是交易编排中枢，职责虽已下降但未完全拆散
  - 真实运行下的慢步骤与失败热点仍需靠观测定位
- **优化待办**
  - [x] 切分为 pipeline steps（便于观测与重试）
  - [x] 增加每步耗时与失败率指标

---

## N13 持仓保护层
- **文件**：`core/engine/protection.py`
- **输入**：实时持仓 + 默认TP/SL阈值
- **输出**：触发平仓市价单（reduce_only）
- **当前实现**
  - 后台线程轮询持仓并按 uplRatio/markPx 强制止盈止损
  - 已支持 per-inst 阈值覆盖，并输出结构化保护事件
- **风险点**
  - 轮询式保护在极端波动下仍受检查频率影响
  - 保护参数仍需按标的波动特征微调
- **优化待办**
  - [x] 支持 per-inst 阈值
  - [x] 强制平仓事件结构化告警

---

## N14 绩效与回测层
- **文件**：`core/data/performance.py`、`core/backtest/simple.py`、`cli_app/backtest_*`
- **输入**：成交记录/历史K线
- **输出**：绩效快照、回测报告、调参建议权重
- **当前实现**
  - `backtest run/report/tune --apply`
  - 回测执行、报告格式化、结果存储已分别拆到 `backtest_execution.py`、`backtest_reporting.py`、`backtest_storage.py`
  - tune 可写入策略权重影响下一轮决策，并已支持多标的聚合、成本模型、regime bucket
- **风险点**
  - 回测撮合仍是近似模型，和真实成交质量必然存在偏差
  - 参数从回测迁移到实盘仍需控制外推风险
- **优化待办**
  - [x] 多标的联合调参
  - [x] 更真实成本模型（点差+滑点）
  - [x] 分市场状态分桶评估

---

## N15 通知与可观测层
- **文件**：`core/utils/notifications.py`、`core/analysis/logger.py`、`logs/*`
- **输入**：执行结果、风险事件、策略信号
- **输出**：Telegram 消息、决策日志、运行日志
- **当前实现**
  - 通知冷却、级别过滤
  - 决策日志 `logs/decisions.jsonl` 已带结构化事件；单轮执行有 `trace_id`
- **风险点**
  - 目前仍以本地日志为主，缺外部聚合与 dashboard
  - 告警维度虽增强，但延迟/错误率/空跑趋势仍主要依赖人工观察
- **优化待办**
  - [x] 每轮执行 trace_id
  - [x] 指标化日志（json structured logs）

---

## 2. 关键数据契约（当前）

- `MarketAnalysis v2`：结构化 `trend/momentum/levels/risk` assessment，兼容旧 `trend_strength/momentum_score/support_levels/resistance_levels/risk_factors`
- `MarketIntelSnapshot v2`：含 `analysis_version/avg_relevance_score/provider_counts/matched_aliases`
- `StrategyContext`：策略输入上下文（inst/timeframe/equity/balance/protection...）
- `TradeSignal`：策略输出（action/confidence/size/reason/protection）
- `ExecutionPlan`：执行输入（order_type/size/price/slippage/blocked/cl_ord_id）
- `Strategy.generate_signal(...)`：除 `analysis_text` 外，可额外接收 `market_analysis`
- `LLMBrain.analyze(...)`：可额外接收 `structured_market_analysis` 与 `structured_market_intel`
- `TradingEngine.run_once` 返回关键字段：
  - `trace_id`
  - `analysis`（确定性分析文本）
  - `analysis_brain`（可选，LLM结构化输出）
  - `market_intel`（可选，新闻情报）
  - `signal`
  - `execution.plan` / `execution.report`
  - `order`

---

## 3. 已完成优化批次（历史）

### 批次 A（稳定性，先做）
- [x] N11 幂等下单 `clOrdId`
- [x] N10 硬风控熔断
- [x] N4 数据新鲜度闸门

### 批次 B（决策质量）
- [x] N8 LLM影响上限
- [x] N7 情报质量与事件标签
- [x] N9 插件冲突仲裁

### 批次 C（性能与维护）
- [x] N12 pipeline 拆分 + 耗时监控
- [x] N15 trace_id + 结构化日志
- [x] N14 多标的联合调参

---

## 4. 使用方式（后续维护）

当前主线已从“节点建设”切到“交付后观测与参数微调”。如果后续重新进入节点开发，每次只选 **1 个节点**，按固定模板推进：

1) 先定义节点目标（成功判据）
2) 写最小变更
3) 增加对应测试
4) dry-run 验证
5) 完成后更新 `docs/SESSION_STATE.md`、`docs/DECISIONS.md`、`docs/NEXT_STEP.md`
6) 再进入下一个节点

这样可以避免“大改后不可控”。

---

## 5. 新开线程恢复（防上下文超限）

新开线程时，先让 Codex 读取以下 3 个文件：

- `docs/SESSION_STATE.md`（当前状态）
- `docs/DECISIONS.md`（关键决策）
- `docs/NEXT_STEP.md`（下一步动作）

建议直接粘贴这一句：

> 请先读取 docs/SESSION_STATE.md、docs/DECISIONS.md、docs/NEXT_STEP.md，然后按 NEXT_STEP 执行。
