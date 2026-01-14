# 重构计划：删除 LLM 功能，增强市场分析

**生成时间**：2026-01-14
**方案**：方案 A（渐进式模块化替换）
**工作量估算**：8-15 人日

---

## 📐 总体架构变更

### 当前架构
```
行情采集 → LLMService.analyze() → Strategy.generate_signal() → RiskManager → 执行
```

### 目标架构
```
行情采集 → MarketAnalyzer.analyze() → Strategy.generate_signal() → RiskManager → 执行
```

---

## 📂 文件清单

### 需要删除的文件
- `core/strategy/llm.py` (758 行)
- `logs/llm-cache.json`（运行时缓存）
- `logs/llm-decisions.jsonl`（决策日志）

### 需要新增的文件
- `core/analysis/__init__.py`（新模块）
- `core/analysis/market.py`（市场分析器，替代 LLMService）
- `core/analysis/indicators.py`（新增指标计算）
- `core/analysis/structure.py`（市场结构分析）
- `core/analysis/logger.py`（决策日志，从 llm.py 迁移）

### 需要修改的文件
- `config/settings.py`（删除 AISettings）
- `requirements.txt`（删除 openai，增加 scipy）
- `main.py`（替换 LLMService 为 MarketAnalyzer）
- `core/engine/trading.py`（修改分析调用链路）
- `core/engine/risk.py`（移除 LLMView 依赖）
- `core/strategy/core.py`（重命名 LLMView 为 AnalysisView）
- `core/data/features.py`（增加新指标）
- `core/__init__.py`（更新导出）

---

## 🏗️ 阶段 1：删除 LLM 依赖（优先级最高）

### 目标
彻底移除 LLM 相关代码、配置、依赖，建立新的市场分析模块。

### 步骤 1.1：创建新的分析模块

**新建 `core/analysis/__init__.py`**
```python
"""市场分析模块（替代 LLM 分析）"""

from .market import MarketAnalyzer, MarketAnalysis
from .logger import DecisionLogger, DecisionRecord

__all__ = [
    "MarketAnalyzer",
    "MarketAnalysis",
    "DecisionLogger",
    "DecisionRecord",
]
```

**新建 `core/analysis/market.py`**
- 创建 `MarketAnalysis` 数据类（替代 `LLMAnalysis`）
- 创建 `MarketAnalyzer` 类（替代 `LLMService`）
- 实现 `analyze()` 方法，返回结构化分析结果
- 初期实现：复用现有 `build_market_summary()`，生成简单的分析文本

**新建 `core/analysis/logger.py`**
- 从 `core/strategy/llm.py` 迁移 `DecisionLogger`、`DecisionRecord`
- 迁移 `build_performance_hint()` 函数
- 迁移性能缓存逻辑（`_performance_cache`）

### 步骤 1.2：修改配置

**修改 `config/settings.py`**
- 删除 `AISettings` 类（包含所有 LLM 提供商配置）
- 从 `AppSettings` 中移除 `ai` 字段
- 更新 `get_settings()` 函数

**修改 `requirements.txt`**
- 删除 `openai==2.8.0`
- 增加 `scipy`（用于市场结构分析）

### 步骤 1.3：修改主程序

**修改 `main.py`**
- 导入：`from core.analysis import MarketAnalyzer, DecisionLogger`
- 初始化：`analyzer = MarketAnalyzer(settings)`（替代 `llm = LLMService(...)`）
- 传递给引擎：`TradingEngine(okx, analyzer, strategy, ...)`
- UI 文案：将"LLM 分析"改为"市场分析"

### 步骤 1.4：修改交易引擎

**修改 `core/engine/trading.py`**
- 导入：`from core.analysis import MarketAnalyzer, DecisionLogger, DecisionRecord`
- 构造函数：参数改为 `analyzer: MarketAnalyzer`
- 调用：`self.analyzer.analyze(...)`（替代 `self.deepseek.analyze(...)`）
- 保持接口兼容：返回值结构不变

### 步骤 1.5：修改策略模块

**修改 `core/strategy/core.py`**
- 重命名类型：`LLMView` → `AnalysisView`
- 重命名类：`LLMInterpreter` → `AnalysisInterpreter`
- 更新 `parse()` 方法：不再解析 JSON，改为解析结构化文本
- 保持 `generate_signal()` 接口不变
- 保持 `enable_llm_analysis` 配置名（含义改为"启用分析"）

### 步骤 1.6：修改风控模块

**修改 `core/engine/risk.py`**
- 导入：`from core.strategy.core import AnalysisView`（替代 `LLMView`）
- 更新函数签名：`_apply_llm_risk(analysis_view: AnalysisView, ...)`
- 保持逻辑不变

### 步骤 1.7：更新模块导出

**修改 `core/__init__.py`**
```python
from .analysis import MarketAnalyzer  # 替代 LLMService
from .strategy.core import Strategy
from .engine.trading import TradingEngine

__all__ = [
    "AppSettings",
    "get_settings",
    "OKXClient",
    "MarketDataStream",
    "MarketAnalyzer",  # 更新
    "Strategy",
    "TradingEngine",
]
```

### 步骤 1.8：删除旧文件

```bash
rm core/strategy/llm.py
rm logs/llm-cache.json
rm logs/llm-decisions.jsonl
```

### 验证方法
1. 运行 `python -m pytest`（如果有测试）
2. 运行 `python main.py --dry-run`（模拟运行）
3. 检查导入错误：`python -c "from core import MarketAnalyzer"`
4. 检查配置加载：`python -c "from config.settings import get_settings; print(get_settings())"`

---

## 🏗️ 阶段 2：增强技术指标（快速见效）

### 目标
在 `core/data/features.py` 中增加 5 类新指标，提升信号质量。

### 步骤 2.1：增加新指标计算

**修改 `core/data/features.py`**

增加以下指标：

1. **Stochastic Oscillator（随机指标）**
   ```python
   from ta.momentum import StochasticOscillator

   stoch = StochasticOscillator(
       high=df["high"], low=df["low"], close=df["close"],
       window=14, smooth_window=3
   )
   df["stoch_k"] = stoch.stoch()
   df["stoch_d"] = stoch.stoch_signal()
   ```

2. **KDJ（基于 Stochastic 派生）**
   ```python
   df["kdj_j"] = 3 * df["stoch_k"] - 2 * df["stoch_d"]
   ```

3. **CCI（商品通道指标）**
   ```python
   from ta.trend import CCIIndicator

   df["cci"] = CCIIndicator(
       high=df["high"], low=df["low"], close=df["close"],
       window=20
   ).cci()
   ```

4. **ADX（趋势强度指标）**
   ```python
   from ta.trend import ADXIndicator

   adx = ADXIndicator(
       high=df["high"], low=df["low"], close=df["close"],
       window=14
   )
   df["adx"] = adx.adx()
   df["adx_pos"] = adx.adx_pos()
   df["adx_neg"] = adx.adx_neg()
   ```

5. **Williams %R**
   ```python
   from ta.momentum import WilliamsRIndicator

   df["williams_r"] = WilliamsRIndicator(
       high=df["high"], low=df["low"], close=df["close"],
       lbp=14
   ).williams_r()
   ```

6. **Ichimoku（一目均衡表）**
   ```python
   from ta.trend import IchimokuIndicator

   ichimoku = IchimokuIndicator(
       high=df["high"], low=df["low"],
       window1=9, window2=26, window3=52
   )
   df["ichimoku_a"] = ichimoku.ichimoku_a()
   df["ichimoku_b"] = ichimoku.ichimoku_b()
   df["ichimoku_base"] = ichimoku.ichimoku_base_line()
   df["ichimoku_conv"] = ichimoku.ichimoku_conversion_line()
   ```

### 步骤 2.2：更新信号生成逻辑

**修改 `core/strategy/core.py` 的 `ObjectiveSignalGenerator._indicator_opinion()`**

增加新指标的判断逻辑：

1. **Stochastic/KDJ 判断**
   - 超卖区（K < 20）金叉 → 买入信号
   - 超买区（K > 80）死叉 → 卖出信号

2. **CCI 判断**
   - CCI < -100 → 超卖，买入信号
   - CCI > 100 → 超买，卖出信号

3. **ADX 趋势强度**
   - ADX > 25 → 强趋势
   - 根据 +DI/-DI 判断方向

4. **Williams %R 判断**
   - W%R < -80 → 超卖
   - W%R > -20 → 超买

5. **Ichimoku 判断**
   - 价格在云上方 → 看涨
   - 价格在云下方 → 看跌
   - 转换线与基准线交叉 → 信号

### 步骤 2.3：更新 MarketAnalyzer

**修改 `core/analysis/market.py`**

在 `_compose_analysis_text()` 中增加新指标的展示：
```python
def _compose_analysis_text(self, ...) -> str:
    latest = features.iloc[-1]
    sections = []

    # 趋势分析
    adx = latest.get("adx", 0)
    sections.append(f"**趋势强度**：ADX={adx:.1f}")

    # 动量分析
    stoch_k = latest.get("stoch_k", 50)
    stoch_d = latest.get("stoch_d", 50)
    sections.append(f"**随机指标**：K={stoch_k:.1f}, D={stoch_d:.1f}")

    # CCI
    cci = latest.get("cci", 0)
    sections.append(f"**CCI**：{cci:.1f}")

    # ... 其他指标 ...

    return "\n".join(sections)
```

### 验证方法
1. 打印新增指标：`python -c "from core.data.features import candles_to_dataframe; ..."`
2. 检查信号生成：运行回测或模拟交易
3. 对比新旧信号质量

---

## 🏗️ 阶段 3：多周期和结构分析（逐步迭代）

### 目标
实现多周期趋势强度、共振检测、支撑/阻力位识别、趋势线绘制。

### 步骤 3.1：多周期趋势强度

**新建 `core/analysis/indicators.py`**

实现以下函数：

1. **`calculate_trend_strength()`**
   - 输入：features, higher_features
   - 输出：趋势强度（0-1）
   - 算法：综合 ADX、EMA 斜率、MACD 柱状图、多周期一致性

2. **`calculate_multi_timeframe_consistency()`**
   - 输入：features, higher_features
   - 输出：一致性评分（0-1）
   - 算法：统计多周期趋势方向的一致性

3. **`get_trend_direction()`**
   - 输入：features
   - 输出：趋势方向（1=上涨，-1=下跌，0=震荡）
   - 算法：基于 EMA 快慢线

4. **`detect_divergence()`**
   - 输入：features
   - 输出：背离描述（顶背离/底背离/无）
   - 算法：对比价格趋势与 RSI 趋势

### 步骤 3.2：市场结构分析

**新建 `core/analysis/structure.py`**

实现以下函数：

1. **`find_support_resistance()`**
   - 输入：features, lookback, tolerance
   - 输出：支撑位列表、阻力位列表
   - 算法：
     - 找到局部高点和低点（`scipy.signal.argrelextrema`）
     - 聚类相近的价格水平
     - 按触及次数排序

2. **`find_local_extrema()`**
   - 输入：data, mode（max/min）
   - 输出：极值点列表
   - 算法：使用 scipy 的 argrelextrema

3. **`cluster_price_levels()`**
   - 输入：prices, tolerance
   - 输出：聚类后的价格水平及强度
   - 算法：按容差合并相近价格

4. **`find_trendlines()`**（可选）
   - 输入：features
   - 输出：上升趋势线、下降趋势线
   - 算法：
     - 找到摆动高点和低点
     - 线性回归拟合趋势线
     - 验证触及次数

### 步骤 3.3：集成到 MarketAnalyzer

**修改 `core/analysis/market.py`**

在 `analyze()` 方法中调用新函数：
```python
from .indicators import calculate_trend_strength, detect_divergence
from .structure import find_support_resistance

def analyze(self, ...) -> MarketAnalysis:
    # ... 现有代码 ...

    # 趋势强度分析
    trend_strength = calculate_trend_strength(features, higher_features)

    # 背离检测
    divergence = detect_divergence(features)
    if divergence:
        risk_factors.append(divergence)

    # 支撑/阻力位
    support_levels, resistance_levels = find_support_resistance(features)

    # 更新分析文本
    analysis_text = self._compose_analysis_text(
        ..., trend_strength, support_levels, resistance_levels, ...
    )

    return MarketAnalysis(
        text=analysis_text,
        summary=summary_text,
        history_hint=history_hint,
        trend_strength=trend_strength,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        risk_factors=risk_factors,
        # ...
    )
```

### 步骤 3.4：更新策略使用结构化数据

**修改 `core/strategy/core.py`**

在 `AnalysisInterpreter.parse()` 中解析结构化数据：
```python
def parse(self, analysis: MarketAnalysis) -> AnalysisView:
    """解析市场分析结果"""

    # 基于趋势强度和动量评分生成信号
    if analysis.trend_strength > 0.7 and analysis.momentum_score > 0.5:
        action = SignalAction.BUY
        confidence = min(analysis.trend_strength, 0.9)
    elif analysis.trend_strength > 0.7 and analysis.momentum_score < -0.5:
        action = SignalAction.SELL
        confidence = min(analysis.trend_strength, 0.9)
    else:
        action = SignalAction.HOLD
        confidence = 0.5

    # 风险因素降低置信度
    if analysis.risk_factors:
        confidence *= 0.8

    return AnalysisView(
        action=action,
        confidence=confidence,
        reason=analysis.text,
        risk="; ".join(analysis.risk_factors),
        raw_text=analysis.text
    )
```

### 验证方法
1. 单元测试：测试各个函数的输出
2. 可视化验证：绘制支撑/阻力位、趋势线
3. 回测验证：对比新旧策略的表现

---

## 🚀 阶段 4：代码优化与审查

### 目标
清理冗余代码，优化性能，确保代码质量。

### 步骤 4.1：清理冗余代码

- 删除 `core/strategy/core.py` 中的历史遗留代码
- 统一命名规范（LLM → Analysis）
- 移除未使用的导入和变量

### 步骤 4.2：性能优化

- 缓存支撑/阻力位计算结果（避免重复计算）
- 优化指标计算（向量化操作）
- 减少不必要的数据复制

### 步骤 4.3：代码审查

使用多模型并行审查：
- Codex：关注安全、性能、错误处理
- Gemini：关注可访问性、设计一致性（如果可用）

---

## ✅ 阶段 5：质量审查与交付

### 验收标准

1. **功能完整性**
   - ✅ LLM 相关代码完全删除
   - ✅ 新增 5 类技术指标
   - ✅ 多周期趋势强度分析
   - ✅ 支撑/阻力位识别
   - ✅ 决策日志功能保留

2. **代码质量**
   - ✅ 无导入错误
   - ✅ 无运行时错误
   - ✅ 代码风格一致
   - ✅ 注释清晰

3. **性能要求**
   - ✅ 分析延迟 < 2 秒
   - ✅ 内存占用无明显增加

4. **文档更新**
   - ✅ README.md 更新架构图
   - ✅ 配置说明更新（删除 AI 配置）
   - ✅ 代码注释完整

### 回滚方案

如果出现严重问题，可以回滚到当前版本：
```bash
git checkout master
git reset --hard <commit-hash>
```

建议在开始前创建备份分支：
```bash
git checkout -b backup-before-refactor
git checkout master
```

---

## 📊 工作量估算

| 阶段 | 任务 | 估算（人日） |
|------|------|-------------|
| 1 | 删除 LLM 依赖 | 2-3 |
| 2 | 增强技术指标 | 1-2 |
| 3 | 多周期和结构分析 | 3-6 |
| 4 | 代码优化与审查 | 1-2 |
| 5 | 质量审查与交付 | 1-2 |
| **总计** | | **8-15** |

---

## 🎯 关键风险点

1. **接口兼容性**
   - 风险：修改接口导致下游模块报错
   - 缓解：保持接口形状不变，逐步重命名

2. **信号质量下降**
   - 风险：删除 LLM 后信号质量不如预期
   - 缓解：增强技术指标，逐步迭代

3. **性能问题**
   - 风险：新增计算导致延迟增加
   - 缓解：缓存结果，优化算法

4. **回归 bug**
   - 风险：修改导致现有功能异常
   - 缓解：充分测试，保留回滚方案

---

## 📝 下一步行动

1. **用户确认计划**：等待用户批准后开始实施
2. **创建备份分支**：`git checkout -b backup-before-refactor`
3. **开始阶段 1**：删除 LLM 依赖
4. **逐步验证**：每完成一个阶段进行验证
5. **最终交付**：完成所有阶段后提交代码

---

**计划状态**：✅ 已完成，等待用户批准
