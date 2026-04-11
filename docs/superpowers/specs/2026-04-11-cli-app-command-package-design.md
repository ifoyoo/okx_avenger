# CLI App Command Package Design

## 背景

当前 [`cli.py`](/Users/t/Desktop/Python/okx/cli.py) 约 1000+ 行，混合了承担以下职责：

- CLI 参数结构定义
- 命令分发
- runtime/context 组装
- `once/run/status/config-check` 运行命令
- `strategies` 策略运维命令
- `backtest` 回测与调参命令
- heartbeat / 回测结果文件等辅助读写

这与已经确认的方向相冲突：`cli.py` 需要继续作为唯一真实入口，但不应继续做一个过载的大文件。

## 目标

- 保留 `cli.py` 作为唯一真实入口文件。
- 将 CLI 组织为显式命令包，而不是继续把实现堆在单文件里。
- 让 parser 注册、命令实现、runtime 辅助职责分离。
- 为下一轮继续删改命令、调整参数、移除冗余显示提供稳定边界。

## 非目标

- 不修改 `./okx -> cli.py` 启动链路。
- 不引入第二个应用入口。
- 不在这一轮重写 CLI 的整体 UX。
- 不做目录扫描式自动发现注册。
- 不修改 `README.md`。

## 约束

- `cli.py` 仍是唯一入口，`python cli.py ...` 与 `./okx ...` 必须继续可用。
- 现有顶层命令名继续保留：`once/run/status/config-check/backtest/strategies`。
- 允许内部实现符号迁移；测试应面向用户契约，而不是依赖 `cli.py` 内部函数位置。
- 重构优先，不保留重复分发路径或旧入口兜底。

## 目标结构

新增顶层包 `cli_app/`，而不是把 CLI 入口层塞进 `core/`。

原因：

- `core/` 目前承载交易域逻辑，CLI 更像应用壳层。
- 仓库已存在 [`cli.py`](/Users/t/Desktop/Python/okx/cli.py)，不能再建同名 `cli/` 包。
- `cli_app/` 可以清晰表达“唯一入口文件 + 内部命令包”的结构。

建议目录：

```text
cli.py
cli_app/
  __init__.py
  parser.py
  registry.py
  context.py
  helpers.py
  commands/
    __init__.py
    runtime.py
    config.py
    strategies.py
    backtest.py
```

各文件职责：

- `cli.py`
  - 极薄入口，只保留 `main()`、`__main__`、必要兼容导出。
- `cli_app/__init__.py`
  - 暴露 `build_parser()`、`main()`。
- `cli_app/parser.py`
  - 创建根 parser，并调用 registry 挂载所有命令组。
- `cli_app/registry.py`
  - 维护显式命令注册顺序。
- `cli_app/context.py`
  - 放 `RuntimeBundle`、logger 初始化、runtime 构建。
- `cli_app/helpers.py`
  - 放 heartbeat、watchlist entry 解析、回测文件读写、通用格式化。
- `cli_app/commands/runtime.py`
  - 放 `once/run/status`。
- `cli_app/commands/config.py`
  - 放 `config-check`。
- `cli_app/commands/strategies.py`
  - 放 `strategies` 所有子命令。
- `cli_app/commands/backtest.py`
  - 放 `backtest run/report/tune`。

## 注册与分发模型

采用“显式 registry + 命令模块自注册”。

`cli_app/registry.py` 提供一份固定注册表，例如：

- `register_runtime_commands`
- `register_config_commands`
- `register_strategy_commands`
- `register_backtest_commands`

`cli_app/parser.py` 负责：

1. 创建根 `ArgumentParser`
2. 创建一级 `subparsers`
3. 按固定顺序调用 registry 中的注册函数

每个命令模块负责：

- 定义自己的 handler
- 创建自己的 parser / subparser
- 通过 `set_defaults(func=handler)` 绑定处理函数

这样可以避免两类问题：

- 避免目录扫描式自动发现带来的调试不确定性
- 避免 parser 和 handler 分散到没有约束的多个入口

## 兼容策略

对外兼容：

- 保留 `python cli.py ...`
- 保留 `./okx ...`
- 保留现有顶层命令名
- 保留主要参数名与主帮助结构

内部兼容：

- 不保证 `cli.py` 继续暴露 `cmd_status`、`cmd_backtest_run` 这类内部实现函数
- 测试会改成验证真实入口契约：
  - `cli.main(...)`
  - `cli.build_parser()`
  - `okx` 启动脚本目标
  - `--help` 输出与参数解析

## 拆分顺序

采用分批迁移，而不是一次性整体搬空。

### 第 1 批：parser 迁移

- 先抽 `build_parser()` 到 `cli_app/parser.py`
- 引入 `cli_app/registry.py`
- 保持 handler 仍暂时在原位也可以，只先把 parser 结构独立出来

目的：

- 先稳定参数解析边界
- 让之后的命令迁移都围绕 registry 进行

### 第 2 批：轻量命令迁移

- 迁移 `status`
- 迁移 `config-check`
- 抽取 heartbeat / ratio / snapshot 相关 helper

目的：

- 先处理依赖面较小、验证便宜的命令

### 第 3 批：runtime 命令迁移

- 迁移 `once`
- 迁移 `run`
- 抽取 `RuntimeBundle`、runtime 构建、watchlist entry 解析

目的：

- 把“运行上下文 + 调度执行”从入口文件中拿出去

### 第 4 批：运维命令迁移

- 迁移 `strategies`
- 迁移 `backtest run/report/tune`
- 抽取回测结果文件读写与调参 helper

目的：

- 收掉 `cli.py` 中剩余最大体积的一块

### 第 5 批：入口收尾

- `cli.py` 缩减为极薄入口
- 清理无主辅助函数
- 确认只保留必要兼容导出

## 错误处理原则

- 参数错误继续交给 `argparse` 自身处理。
- 运行期错误仍由各 handler 维持当前语义：
  - `once/run` 继续写 heartbeat 状态
  - API/回测拉取失败继续按当前命令粒度记录 warning 或返回非零
  - `KeyboardInterrupt` 在 `run` 中继续转为正常停止
- 本次重构不新增统一异常包装器，避免改变现有退出码和日志行为。

## 测试策略

先补入口/解析契约测试，再做迁移。

重点覆盖：

- `cli.main(["status"])` 仍能完成分发
- `build_parser()` 仍能解析 `once` / `config-check` / `strategies` / `backtest`
- `./okx` 仍指向 `cli.py`
- `python cli.py --help` 正常
- `./okx --help` 正常

如有必要，补充新的 parser registry 测试，验证：

- 所有顶层命令都已注册
- `backtest` 与 `strategies` 的子命令仍完整存在

## 风险与应对

### 风险 1：内部 monkeypatch 测试失效

现有测试如果绑定 `cli.py` 中具体 handler 符号，会在迁移后自然失效。

应对：

- 改测试，转而校验入口契约与真实 parser 行为

### 风险 2：参数漂移

拆 parser 时最容易误删默认值、help 文本、`dest`、`required=True`。

应对：

- 先写 parser 回归测试
- 分批迁移，每迁一组就跑 focused tests

### 风险 3：runtime helper 迁移后循环语义漂移

`once/run` 依赖 heartbeat、interval、watchlist entry 解析、bundle 生命周期，任何遗漏都可能造成行为漂移。

应对：

- `once/run` 晚于 parser 与轻量命令迁移
- 保持现有实现语义优先，不做顺手优化

### 风险 4：过度工程

方案 C 很容易演变成自动扫描、装饰器注册、反射式分发，这对当前仓库没有必要。

应对：

- registry 保持显式、静态、可读
- 不引入额外框架层

## 验收标准

完成后应满足：

1. `cli.py` 只剩极薄入口，不再承载大块命令实现。
2. parser 构建通过 `cli_app/parser.py + cli_app/registry.py` 完成。
3. runtime、config、strategies、backtest 命令已迁移到各自模块。
4. `python cli.py --help` 与 `./okx --help` 均返回成功。
5. 现有 focused CLI tests 通过，必要时新增 registry/parser 测试。
6. 不恢复任何旧入口、启动 UI 或确认交互。
