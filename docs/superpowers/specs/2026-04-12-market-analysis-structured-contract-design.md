# Market Analysis Structured Contract Design

## 背景

当前 [`core/analysis/market.py`](/Users/t/Desktop/Python/okx/core/analysis/market.py) 已经从“纯 LLM 文本分析”转向确定性分析，但模块内部仍有两个明显问题：

- 结构化输出过薄。对外只有 `trend_strength`、`momentum_score`、`support_levels`、`resistance_levels`、`risk_factors` 这些粗粒度字段，后续 `fusion` / `llm` 很难稳定消费。
- 文本与分析耦合过深。`_compose_analysis_text()` 直接基于原始指标再次做判断，等于“分析逻辑”和“解释渲染”混在一起，后面修改任何判断规则都容易造成结构字段和文本描述漂移。

这轮不去同时改 `intel`、`fusion`、`llm`，而是先把确定性市场分析本身变成一个稳定、可复用的输入层。

## 目标

- 保留 [`MarketAnalysis`](/Users/t/Desktop/Python/okx/core/analysis/market.py) 现有公开字段，避免调用方和现有测试大面积破坏。
- 为市场分析增加更稳定的结构化组件：趋势、动量、关键位、风险。
- 让文本分析成为结构化组件的渲染结果，而不是另一套平行逻辑。
- 在不新增配置项的前提下，提高趋势/动量/波动/关键位判断的一致性。

## 非目标

- 不修改 `TradingEngine` 的主流程编排。
- 不在这一轮调整 `LLMBrain` prompt 或新闻情报逻辑。
- 不引入新的外部依赖。
- 不把 `market.py` 扩展成新的“大而全策略层”。

## 约束

- `MarketAnalyzer.analyze(...)` 的调用签名保持不变。
- `MarketAnalysis.text/summary/history_hint/trend_strength/momentum_score/support_levels/resistance_levels/risk_factors` 继续可用。
- 现有 [`tests/test_market_analyzer.py`](/Users/t/Desktop/Python/okx/tests/test_market_analyzer.py) 和交易链路对 `MarketAnalysis` 的基本假设不能被打破。
- 本轮重构优先，不保留两套长期并存的分析路径。

## 方案比较

### 方案 A：继续保留当前标量字段，只改善内部公式

优点：

- 改动最小
- 风险低

缺点：

- 结构化契约仍然太薄
- 下游还是只能依赖自由文本和几个粗粒度分数
- 后续 `fusion` / `llm` 仍然拿不到稳定的可解释输入

结论：不推荐。

### 方案 B：在 `market.py` 内增加结构化 assessment dataclass，并让文本只做渲染

优点：

- 兼容现有调用方
- 改动集中在单模块，容易验证
- 为后续阶段提供稳定结构化输入

缺点：

- `market.py` 仍会保留一定体积
- 需要补一批契约测试

结论：推荐。

### 方案 C：直接把市场分析拆成完整子包

优点：

- 边界最清晰

缺点：

- 这一轮 scope 过大
- 容易把“提升分析质量”变成“过早架构拆分”

结论：暂不采用，后续如 assessment 稳定后再考虑。

## 推荐设计

采用方案 B。

### 1. 新增结构化 assessment

在 [`core/analysis/market.py`](/Users/t/Desktop/Python/okx/core/analysis/market.py) 中增加四类内部结构：

- `TrendAssessment`
  - `direction`: `bullish` / `bearish` / `range`
  - `strength`: 0~1
  - `label`: 面向文本渲染的人类可读标签
  - `ema_gap_pct`
  - `adx`
  - `higher_timeframe_alignment`

- `MomentumAssessment`
  - `score`: -1~1
  - `label`
  - `rsi`
  - `macd_bias`
  - `stoch_bias`
  - `williams_bias`

- `LevelAssessment`
  - `supports`
  - `resistances`
  - `nearest_support`
  - `nearest_resistance`
  - `range_position`

- `RiskAssessment`
  - `factors`
  - `volatility_ratio`
  - `regime`: `calm` / `normal` / `hot`
  - `account_pressure`

### 2. `MarketAnalysis` 保持兼容并扩展

`MarketAnalysis` 增加以下新字段：

- `trend`
- `momentum`
- `levels`
- `risk`
- `analysis_version`

同时继续保留旧字段，并由新结构回填：

- `trend_strength <- trend.strength`
- `momentum_score <- momentum.score`
- `support_levels <- levels.supports`
- `resistance_levels <- levels.resistances`
- `risk_factors <- risk.factors`

这样旧调用方不需要立刻改，但后续阶段可以逐步改为消费新的 assessment。

### 3. 分析流程改为“先结构化，后渲染”

`analyze()` 的顺序调整为：

1. 生成 `summary`
2. 生成 `history_hint`
3. 计算 `TrendAssessment`
4. 计算 `MomentumAssessment`
5. 计算 `LevelAssessment`
6. 计算 `RiskAssessment`
7. 用上述 assessment 渲染 `text`
8. 组装 `MarketAnalysis`

重点约束：

- 文本渲染阶段不得重新发明一套判断逻辑
- 结构字段与文本结论必须来自同一 assessment

### 4. 趋势判断改为多信号统一评分

当前趋势强度基本只看 `ema_fast` 和 `ema_slow` 距离，信息太弱。新逻辑合并：

- EMA 快慢线相对位置
- EMA gap 百分比
- ADX 强度
- 高周期方向一致性

输出规则：

- 明确区分 `direction` 和 `strength`
- “强趋势”不再只由单一指标触发
- 高周期如果缺失，不阻断分析，但会降低一致性加分

### 5. 动量判断改为多指标聚合

当前 `momentum_score` 主要基于 RSI。新逻辑改为聚合：

- RSI
- MACD 与 signal 相对位置
- Stoch K / D
- Williams %R

要求：

- `score` 保持在 `[-1, 1]`
- `label` 明确给出 `overbought` / `oversold` / `bullish` / `bearish` / `neutral`

### 6. 风险判断显式区分“市场风险”和“账户风险”

当前风险因素只粗略合并。新逻辑区分：

- 市场风险：高波动、趋势衰减、关键位过近
- 账户风险：可用资金不足、外部 `risk_note`

本轮不把风险 assessment 直接接入 `RiskManager`，但要保证后续可直接消费。

### 7. 文本输出保持简洁但可复盘

文本结构改为：

- 基础信息
- 趋势
- 动量
- 关键位
- 风险
- 综合结论

避免的问题：

- 指标原始值堆砌太多
- 同一结论在多个段落重复
- 文本与结构字段相互矛盾

## 测试策略

重点补四类测试：

1. 契约兼容
   - `MarketAnalysis` 仍保留旧字段
   - 新增 assessment 字段存在且可读

2. 趋势/动量结构
   - 上涨样本得到 `bullish`
   - 下跌样本得到 `bearish`
   - 动量标签与 score 一致

3. 关键位与风险
   - 支撑/阻力保持可识别
   - 高波动/低可用资金等风险继续输出

4. 文本一致性
   - 文本中的趋势/动量/风险描述与 assessment 一致

## 风险与应对

### 风险 1：结构增加后现有测试或调用方依赖旧初始化方式

应对：

- 旧字段全部保留
- 新字段提供默认值

### 风险 2：多指标评分后结果漂移过大

应对：

- 先用 focused tests 锁定方向性与边界
- 不在这一轮直接改策略阈值

### 风险 3：文本渲染仍偷偷夹带新判断

应对：

- 渲染层只消费 assessment
- 专门补“文本与结构一致”的测试
