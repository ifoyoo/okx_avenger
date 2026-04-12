# Intel Relevance Scoring Design

## 背景

当前 [`core/analysis/intel.py`](/Users/t/Desktop/Python/okx/core/analysis/intel.py) 已经支持多源聚合、去重、事件标签和情报闸门，但质量上仍有一个核心短板：

- 资产相关性过滤不统一。CoinGecko 的泛新闻会经过 alias 过滤，而 NewsAPI 基本只依赖查询词，导致短 symbol、模糊别名或泛行业新闻时仍可能混入弱相关内容。
- 聚合逻辑没有把“相关性强弱”显式建模。当前 headline 只记录 sentiment / event_tags / risk_weight，最终 sentiment 和 event weight 聚合也没有考虑文章到底有多相关。

如果这一层不先做好，后续 `fusion` 和 `llm` 拿到的仍然是“真假相关混在一起”的情报输入。

## 目标

- 为所有 provider 统一引入“资产相关性评分”。
- 在 headline 级别暴露相关性和命中的 alias。
- 聚合 sentiment / event risk 时按相关性加权，而不是简单均值。
- 保持现有 `MarketIntelSnapshot` 对外基本兼容。

## 非目标

- 不在这一轮接入新的新闻 provider。
- 不在这一轮引入外部 NLP/embedding 依赖。
- 不直接修改 `RiskManager` 的事件门限策略。

## 约束

- `NewsIntelCollector.collect(...)` 的签名保持不变。
- 现有 `sentiment_score`、`event_tags`、`event_risk_score`、`coverage_count` 继续存在。
- 允许扩展 `NewsHeadline` / `MarketIntelSnapshot` 字段，但不能破坏旧 `to_dict()` 语义。

## 推荐设计

### 1. 统一 relevance scoring

新增统一函数，对所有 provider 的 article 计算：

- `relevance_score`: 0~1
- `matched_aliases`: 命中的 alias 列表

评分来源：

- title 命中 alias：最高权重
- description/content 命中 alias：次高权重
- url / slug 命中 alias：补充权重
- 短 symbol 命中需要更严格条件，避免把普通缩写误当币名

### 2. 全 provider 过滤

不是只对 CoinGecko 做过滤，而是所有 provider 拉回来的 article 都统一过 relevance scoring。

规则：

- `relevance_score` 低于阈值的 article 丢弃
- 对短 alias / 短 symbol 使用更严格阈值
- 去重仍保留，但应在 relevance 计算后进行

### 3. headline 与 snapshot 扩展

扩展 [`NewsHeadline`](/Users/t/Desktop/Python/okx/core/analysis/intel.py)：

- `relevance_score`
- `matched_aliases`

扩展 [`MarketIntelSnapshot`](/Users/t/Desktop/Python/okx/core/analysis/intel.py)：

- `analysis_version`
- `matched_aliases`
- `avg_relevance_score`
- `provider_counts`

### 4. 聚合改为 relevance-weighted

- `sentiment_score` 按 relevance 加权
- `event_tags` 的单篇权重先乘 relevance，再做聚合
- summary 显示 relevance 和 provider coverage，便于复盘

## 测试策略

1. NewsAPI 也会做 alias relevance 过滤
2. headline 暴露 relevance_score / matched_aliases
3. 聚合结果按 relevance 加权，而不是简单平均
4. 现有多 provider / 去重 / source filter 契约继续保持
