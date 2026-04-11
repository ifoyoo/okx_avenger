# OKX 自动交易项目节点清单（执行链路版）

> 目标：把当前项目拆成可独立优化的节点，逐个做“输入-输出-约束-优化”。
>
> 范围：`okx run/once` 实盘链路；`backtest`/`strategies` 作为辅助链路。

---

## 0. 总览（主链路）

```text
CLI(cli.py/okx)
  -> Config(.env -> settings)
  -> Watchlist(manual/auto/mixed)
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
- **风险点**
  - 运行期改 `.env` 依赖显式 `cache_clear`
  - 配置合法性校验偏弱（例如范围、互斥）
- **优化待办**
  - [x] 增加强校验（权重范围、超时范围、URL合法性）
  - [x] 增加配置快照输出（用于故障复盘）

---

## N2 入口与调度层
- **文件**：`cli.py`、`okx`
- **输入**：CLI 参数 + `AppSettings`
- **输出**：单轮执行请求/循环调度
- **当前实现**
  - `okx` 仅作为 shell 包装，统一转调 `cli.py`
  - `cli.py` 提供 `once/run/status/config-check/strategies/backtest`
- **风险点**
  - `cli.py` 同时承担命令装配与运行编排，文件体积仍偏大
  - `run` 常驻调度缺“健康探针/自愈重启”
- **优化待办**
  - [x] 收口为 `cli.py` 单入口并删除 `main.py` 重复调度
  - [x] 增加运行健康状态文件（heartbeat）

---

## N3 标的管理（Watchlist）
- **文件**：`core/data/watchlist_loader.py`、`core/data/auto_watchlist.py`
- **输入**：`watchlist.json`、账户可用资金、ticker/instruments
- **输出**：`[{inst_id,timeframe,higher_timeframes,max_position,protection}]`
- **当前实现**
  - 支持 `manual/auto/mixed`
  - auto 按成交额排序并做最小名义资金过滤
- **风险点**
  - auto 仅看 24h 成交额，缺波动/点差/交易成本约束
  - 资产集中度约束不足
- **优化待办**
  - [x] 加入 spread/波动/最小成交额联合过滤
  - [x] 增加“同一币种暴露上限”

---

## N4 市场数据采集层（REST/WS）
- **文件**：`core/client/rest.py`、`core/client/stream.py`
- **输入**：inst/timeframe/API 凭证
- **输出**：K线、盘口、成交、资金费率、持仓量
- **当前实现**
  - REST 全封装 + `_ensure_success`
  - WS 缓存 candles/books/trades，支持断线重连
- **风险点**
  - REST 限频与退避策略不够细
  - WS/REST 切换后数据一致性无显式校验
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
  - `bfill/ffill` 保证尾行可用
- **风险点**
  - 长窗口指标在小样本场景稳定性一般
  - 指标参数全局固定，未按品种/周期调优
- **优化待办**
  - [x] 引入最小样本约束（不足直接降级）
  - [x] 参数分层（按 timeframe/inst 配置）

---

## N6 市场分析层（确定性）
- **文件**：`core/analysis/market.py`
- **输入**：features + higher_features + snapshot + account/perf
- **输出**：`MarketAnalysis(text, summary, history_hint, ...)`
- **当前实现**
  - 结构化文本 + 趋势/动量/风险因素
- **风险点**
  - 支撑阻力目前仍简化（空实现占位）
  - 文本逻辑与策略解释有冗余
- **优化待办**
  - [x] 完成支撑阻力真实识别算法
  - [x] 文本输出模板化，便于回测解释对齐

---

## N7 新闻/舆情情报层（可选）
- **文件**：`core/analysis/intel.py`
- **输入**：inst_id -> symbol/coin_id、多新闻源 API
- **输出**：`MarketIntelSnapshot(sentiment_score,risk_tags,headlines,summary)`
- **当前实现**
  - `NEWS_ENABLED` 开关
  - `CoinGecko + NewsAPI` 聚合、去重、关键词打分（确定性）
- **风险点**
  - 关键词情绪法较粗糙
  - 小币 `coin_id` 仍建议显式配置，避免误匹配
- **优化待办**
  - [x] 来源白名单/黑名单
  - [x] 更强去重（title+source+time）
  - [x] 事件级标签（监管/安全/宏观）与闸门联动
  - [x] 多源聚合（CoinGecko + NewsAPI）

---

## N8 LLM 分析大脑层（可选）
- **文件**：`core/analysis/llm_brain.py`
- **输入**：确定性分析 + 账户风险 + market_intel
- **输出**：`BrainDecision`（严格 JSON）
- **当前实现**
  - OpenAI 兼容 `/chat/completions`
  - 超时/异常自动回退，无阻塞交易主链
- **风险点**
  - prompt 漂移与输出稳定性
  - LLM 影响边界需更严格（防过度主导）
- **优化待办**
  - [x] 增加影响上限（仅调置信度，不直接反转）
  - [x] 增加响应质量评分与拒绝策略

---

## N9 策略信号层（插件+融合）
- **文件**：`core/strategy/core.py`、`core/strategy/plugins.py`
- **输入**：features、higher_features、analysis_text（可来自LLM）
- **输出**：`StrategyOutput(trade_signal,objective_signals,...)`
- **当前实现**
  - 插件开关与权重：`STRATEGY_SIGNALS_ENABLED/WEIGHTS`
  - 已接入策略：`volume_pressure`、`volatility_breakout`、`bull_trend`、`ma_golden_cross`、`shrink_pullback`、`volume_breakout`、`box_oscillation`、`one_yang_three_yin`
- **风险点**
  - `core.py` 仍较重（已改善但未彻底拆分）
  - 策略间冲突处理仍偏简单
- **优化待办**
  - [x] 拆分 `signals/ fusion/ reasoning` 子模块
  - [x] 引入“策略冲突仲裁规则”与解释标签

---

## N10 风控层
- **文件**：`core/engine/risk.py`
- **输入**：`AccountState` + features + strategy_output
- **输出**：`RiskAssessment(trade_signal,blocked,notes)`
- **当前实现**
  - 账户可用资金占比、流动性、多周期冲突拦截
- **风险点**
  - 缺硬风控闸门（如日内亏损熔断）
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
- **风险点**
  - 下单幂等（`clOrdId`）未强制
  - 订单生命周期管理不完整（部分成交/超时）
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
  - 一轮执行闭环完整
  - 支持 LLM/News 可选增强
- **风险点**
  - 责任仍较集中（抓数、分析、执行都在同类）
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
- **风险点**
  - 阈值单一（全局），缺分标的覆盖
  - 触发后状态回写与告警可加强
- **优化待办**
  - [x] 支持 per-inst 阈值
  - [x] 强制平仓事件结构化告警

---

## N14 绩效与回测层
- **文件**：`core/data/performance.py`、`core/backtest/simple.py`、`cli.py(backtest)`
- **输入**：成交记录/历史K线
- **输出**：绩效快照、回测报告、调参建议权重
- **当前实现**
  - `backtest run/report/tune --apply`
  - tune 可写入策略权重影响下一轮决策
- **风险点**
  - 回测撮合模型简化（滑点/成交约束）
  - 单标的调参偏多标的外推风险
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
  - 决策日志 `logs/decisions.jsonl`
- **风险点**
  - 缺统一 trace id 贯穿单轮执行
  - 告警维度偏少（延迟、错误率、空跑）
- **优化待办**
  - [x] 每轮执行 trace_id
  - [x] 指标化日志（json structured logs）

---

## 2. 关键数据契约（当前）

- `StrategyContext`：策略输入上下文（inst/timeframe/equity/balance/protection...）
- `TradeSignal`：策略输出（action/confidence/size/reason/protection）
- `ExecutionPlan`：执行输入（order_type/size/price/slippage/blocked）
- `TradingEngine.run_once` 返回关键字段：
  - `analysis`（确定性分析文本）
  - `analysis_brain`（可选，LLM结构化输出）
  - `market_intel`（可选，新闻情报）
  - `signal`
  - `execution.plan` / `execution.report`
  - `order`

---

## 3. 推荐优化批次（实际可执行）

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

## 4. 使用方式（建议）

每次只选 **1 个节点**，按固定模板推进：

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
