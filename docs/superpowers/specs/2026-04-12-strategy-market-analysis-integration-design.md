# Strategy Market Analysis Integration Design

## 背景

前两阶段已经完成：

- `market.py` 输出了结构化 `MarketAnalysis v2`
- `intel.py` 输出了更干净的相关性加权情报

但当前 [`core/strategy/core.py`](/Users/t/Desktop/Python/okx/core/strategy/core.py) 仍主要通过 `analysis_text` 这条字符串路径消费分析层输出。对于确定性市场分析，这意味着：

- `AnalysisInterpreter` 往往只能得到 `HOLD + 0.5`
- `MarketAnalysis v2` 的 trend / momentum / risk 结构没有真正进入融合决策

所以第 3 阶段的目标不是“新增更多插件”，而是把已有的结构化分析接入融合层。

## 目标

- `Strategy.generate_signal(...)` 能直接消费 `MarketAnalysis`
- 确定性分析可转成稳定的 `AnalysisView`
- 不破坏现有 LLM JSON 分析路径

## 推荐设计

### 1. `Strategy.generate_signal` 增加可选 `market_analysis`

保持 `analysis_text` 兼容，同时新增 `market_analysis: Optional[object] = None`。

### 2. `AnalysisInterpreter` 增加 `from_market_analysis()`

根据 `trend.direction`、`trend.strength`、`momentum.score`、`risk.factors` 生成：

- `action`
- `confidence`
- `reason`
- `risk`

### 3. 决策优先级

- 若 `analysis_text` 是 LLM JSON，继续优先按现有路径解析
- 若 `analysis_text` 只是确定性文本，且有 `market_analysis`，则优先使用 `from_market_analysis()` 生成的结构化 `AnalysisView`

## 测试策略

- 新增测试锁定 `from_market_analysis()` 的方向输出
- 新增测试锁定 `Strategy.generate_signal(..., market_analysis=...)` 会把 structured analysis 接入 reason/fusion
- 全量测试保持通过
