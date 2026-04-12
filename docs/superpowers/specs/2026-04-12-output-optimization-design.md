# Output Optimization Design

## Goal

在不引入 Rich/TUI、不增加重依赖的前提下，重构项目当前面向人的输出体验，让 `config-check`、`status`、`run/once`、Telegram 通知和 `backtest report` 都遵循同一套表达原则：先结论，后细节，最后原始信息。

## Scope

本轮只优化“输出表达层”，不改变交易决策、回测计算、通知触发时机或配置契约本身。

覆盖范围：

- CLI 摘要输出
- runtime 轮次与单标的日志
- Telegram 通知文案
- backtest / tune 报告输出

明确不做：

- 引入 Rich、TUI、颜色依赖
- 改交易逻辑、策略逻辑、通知级别逻辑
- 新增交互式确认

## Current Problems

### 1. CLI 输出像多个子系统各写一套

`config-check`、`status`、`backtest report` 的标题、字段命名、分组方式不统一。用户看到的是零散字段，而不是“我现在能不能跑、跑得怎么样”。

### 2. runtime 日志同时承担“人类阅读”和“程序排错”

现在日志已经有结构化信息，但轮次摘要和单标的执行结果没有统一层级。用户需要自己拼出“本轮到底是成功、观望、阻断还是失败”。

### 3. Telegram 更像日志转发，不像移动端警报

通知虽然已经接回主链路，但文案仍偏事件原样转发，缺少适合手机场景的短格式：标题、关键事实、原因。

### 4. 回测输出缺结论层

表格能看，但没有先给“这组结果值不值得继续看”的结论摘要。输出更像数据 dump，不像报告。

## Design Principles

### Principle 1: Summary First

每个输出面都先告诉用户结论，而不是先丢字段：

- `config-check`: ready / warning / failed
- `status`: current snapshot
- `run/once`: cycle summary
- Telegram: alert headline
- `backtest`: report summary

### Principle 2: One Concept, One Label

跨输出面尽量统一术语，不再让同一概念出现多套叫法。

统一目标词汇：

- `inst`
- `tf`
- `action`
- `conf`
- `blocked`
- `failed`
- `reason`
- `status`

### Principle 3: Human View vs Debug View Separation

CLI 输出优先给人看，logger 输出优先给排错看，Telegram 输出优先给手机看。三者使用同一份事实，但不能互相原样复制。

### Principle 4: Dense, Not Noisy

不做花哨界面，但也不保留无意义空行和冗长句子。输出需要紧凑、稳定、可扫读。

## Output Contracts

### A. `config-check`

目标：一眼看出“能不能启动，哪些能力是开着的，哪些只是关闭不是故障”。

结构：

1. 总状态行
2. `Account`
3. `Runtime`
4. `Notify`
5. `LLM`
6. `Intel`
7. 可选补充信息（snapshot / api-check）

示意：

```text
CONFIG READY
Account  base_url=https://www.okx.com
Runtime  interval=5m leverage=10.0
Notify   on level=orders
LLM      on model=gemini-2.5-flash
Intel    on providers=coingecko,newsapi
snapshot data/config_snapshot.json
```

要求：

- 不再以纯字段堆叠开头
- “关闭”与“缺失/失败”分开表达
- 每组只保留最关键字段

### B. `status`

目标：一眼看出当前账户、watchlist、持仓、heartbeat。

结构：

1. `=== Runtime Status ===`
2. `Account`
3. `Watchlist`
4. `Positions`
5. `Heartbeat`

要求：

- watchlist 每项紧凑，突出 `inst` 和 `tf`
- position 统一成一行摘要
- heartbeat 强调 `status / cycle / exit_code / updated_at`

### C. `run/once` runtime 日志

目标：把“每轮结果”从散日志中提炼出来。

保留两层：

1. cycle start / cycle summary
2. per-inst result

cycle summary 固定统计：

- total
- completed
- blocked
- hold
- failed

per-inst result 固定重点：

- inst / tf
- action / conf
- execution outcome
- short reason

要求：

- 正常路径压缩
- 阻断和失败展开
- 不在同一条里混入过多附属上下文

### D. Telegram

目标：适合手机 3 秒内读完。

模板：

- 第一行：事件标题
- 第二行：`inst/tf/action/conf`
- 第三行：原因或错误码

示意：

```text
[ORDER FAILED]
BTC-USDT-SWAP 5m BUY conf=0.82
code=51000 msg=insufficient margin
```

要求：

- 保持纯文本
- 不复制整条 logger message
- 同类事件模板稳定

### E. `backtest report` / `tune`

目标：先给结论，再给表格，再给样本。

结构：

1. report summary
2. scoreboard / summary table
3. trades sample 或 regime buckets

要求：

- `backtest report` 新增总结性首屏
- `tune` 输出强化排序结果和 regime 可读性
- trade sample 每行仍保持紧凑

## File Boundaries

- `cli_app/config_reporting.py`
  负责 `config-check` 的人类可读摘要，不处理配置校验逻辑。
- `cli_app/runtime_reporting.py`
  负责 runtime status 页面的拼装结构。
- `cli_app/runtime_status_helpers.py`
  负责状态页各 section 的细节文本。
- `cli_app/runtime_execution.py`
  负责 runtime 周期日志文案与摘要节奏。
- `core/utils/notifications.py`
  负责通知模板和事件渲染。
- `cli_app/backtest_reporting.py`
  负责 backtest/tune 报告文本格式。
- `cli_app/backtest_helpers.py`
  负责 summary 打印入口，必要时下沉到 reporting 中统一。

## Testing Strategy

本轮以输出契约测试为主，不做 snapshot 文件。

需要新增或调整的测试类型：

- `config_reporting`：校验新的 grouped summary 结构
- `runtime_reporting/status_helpers`：校验标题、字段和空状态输出
- `runtime_execution`：校验 cycle summary 文案
- `notifications`：校验模板渲染结果
- `backtest_reporting`：校验 report summary / trade lines / tune lines

## Risks

### Risk 1: 测试对具体文案过度耦合

处理方式：锁定输出契约与关键行，而不是每个空格都做脆弱断言。

### Risk 2: CLI 与 logger 语义不一致

处理方式：先统一契约词汇，再分别渲染，不直接复用同一原始句子。

### Risk 3: 通知模板过短导致信息不足

处理方式：标题 + 核心事实 + 原因三行结构固定保留，不再继续压缩。
