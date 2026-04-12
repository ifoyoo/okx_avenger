# LLM Structured Context Design

## 背景

现在：

- `MarketAnalysis v2` 已结构化
- `MarketIntelSnapshot v2` 已有 relevance metadata
- 但 [`core/analysis/llm_brain.py`](/Users/t/Desktop/Python/okx/core/analysis/llm_brain.py) 仍主要吃长文本和原始 dict dump

这会削弱前面三阶段的收益，因为 LLM 还得自己从长文本里再解析一次结构。

## 目标

- 给 `LLMBrain` 显式输入 compact structured market context
- 给 `LLMBrain` 显式输入 compact structured intel context
- 不破坏现有 `analyze(...)` 调用兼容性

## 推荐设计

- `LLMBrain.analyze(...)` 增加可选 structured context 参数
- prompt 中新增 `structured_market_analysis` 和 `structured_market_intel`
- 保留旧 `deterministic_summary` / `deterministic_analysis`，但它们降级为补充说明，而不是唯一结构来源
