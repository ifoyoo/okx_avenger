# OKX DeepSeek 量化引擎

> 结合 OKX 官方 Python SDK、WebSocket 行情、DeepSeek/OpenAI 家族 LLM、客观指标策略与严控执行链条的多周期自动化交易框架。

---

## 项目亮点

- **端到端自动化**：`main.py` 通过 Rich 动画确认 → watchlist 并发调度 → LLM/策略/风控 → 执行/通知，全程每 `RUN_INTERVAL_MINUTES` 分钟循环。
- **多维行情输入**：`core/data_pipeline.py` 聚合 OKX REST + WebSocket 的 K 线、盘口、实时成交、资金费率、持仓量，转成可读摘要供 LLM/策略使用。
- **LLM 智能分析**：`core/analysis.py` 支持 DeepSeek/OpenAI/Azure/Qwen/Moonshot/Grok，可批量请求、带历史胜率提示并做磁盘缓存/落盘评估。
- **客观指标融合**：`core/strategy.py` 将 RSI/EMA/MACD/Bollinger/ATR 等客观指标、LLM JSON、波动/流动性过滤及 PositionSizer 组合成可执行信号。
- **三层风控 + 精细执行**：`core/risk.py`（账户/品种/信号）、`core/execution.py`（合约规格、止盈止损附带、滑点控制）、`core/performance.py`（近期盈亏快照）闭环。
- **智能 watchlist**：`core/watchlist_loader.py` 支持手动/自动/混合；`core/auto_watchlist.py` 结合 24h 成交额、账户可用资金、杠杆与最小张数动态筛币。
- **可观测性完备**：Rich 控制台、Loguru 滚动日志、`logs/llm-decisions.jsonl` 决策记录、`data/perf_cache.json` 绩效缓存、Telegram 冷却通知、`data/auto_watchlist.json` 与 `logs/llm-cache.json` 缓存全可追溯。

---

## 系统架构

```text
┌────────────┐   ┌──────────────────────────────────────────────┐
│watchlist   │   │MarketDataStream + OKX REST (core/client.py)  │
│manual/auto │──▶ Kline/OrderBook/Trades/Funding/OI             │
└────┬───────┘   └───────────────┬──────────────────────────────┘
     │                           │
     │                  ┌────────▼────────┐
     │                  │Feature Builder  │ candles_to_dataframe +
     │                  │(core/data_utils)│ indicators / volatility
     │                  └────────┬────────┘
     │                           │
┌────▼───────┐    ┌──────────────▼─────────────┐
│Watchlist   │    │MarketSnapshotCollector     │
│Manager     │    │+ build_market_summary      │
│(manual/auto│    └──────────────┬─────────────┘
└────┬───────┘                   │ snapshot text
     │                           │
     │                    ┌──────▼──────┐ LLMService
     │ signals            │LLM 批量/缓存│ (core/analysis.py)
     │                    └──────┬──────┘
     │                           │ JSON行动 + summary + history
┌────▼───────┐           ┌───────▼────────┐
│Strategy    │           │RiskManager      │
│(objective +│──────────▶│+ PositionSizer  │
│LLM fusion) │           └───────┬────────┘
└────┬───────┘                   │
     │ trade signal              │风控后信号
     │                           ▼
                           ┌────────────┐
                           │Execution   │ attaches TP/SL, size/lot
                           │Engine      │ + PerformanceTracker
                           └────┬───────┘
                                │
                          ┌─────▼─────┐
                          │Trading    │ send order, log decision,
                          │Engine     │ notify, schedule loop
                          └───────────┘
```

---

## 目录导览

| 路径 | 说明 |
| --- | --- |
| `main.py` | CLI 主入口，负责 Rich 交互、线程池调度、定时调度。 |
| `config/` | `settings.py` 定义 Pydantic Settings（账户、AI、策略、运行、通知），`.env` 自动加载。 |
| `core/client.py` | 封装 OKX REST Account/Trade/Market/Public API 并做错误包装。 |
| `core/data_utils.py` | OKX K 线 → Pandas + RSI/EMA/MACD/ATR/布林/收益率/波动指标。 |
| `core/data_pipeline.py` | 行情摘要 + 盘口/成交/衍生品快照 + 多周期描述。 |
| `core/analysis.py` | LLM 批量请求、缓存、历史胜率提示、决策日志。 |
| `core/strategy.py` | 客观信号、LLM JSON 解析、信号融合、动态风控提示、保护价生成。 |
| `core/positioning.py` | PositionSizer，基于权益/可用资金/ATR/信号置信度调仓。 |
| `core/risk.py` | 账户风控（可用资金占比/交易所风控）、流动性、波动、趋势冲突。 |
| `core/execution.py` | 合约规格缓存、张数折算、滑点评估、TP/SL 附单、执行报告。 |
| `core/performance.py` | 最近 N 天成交抓取、盈亏/胜率/手续费统计缓存。 |
| `core/watchlist_loader.py` / `core/auto_watchlist.py` | 手动 + 自动 watchlist 聚合、资金过滤。 |
| `core/market_stream.py` | WebSocket 缓存 K 线/盘口/成交，REST 不足时自动回退。 |
| `core/notifications.py` | Telegram 冷却推送。 |
| `data/` | `perf_cache.json`、`auto_watchlist.json` 等运行时缓存。 |
| `logs/` | 滚动日志、LLM 决策、LLM 缓存、运行日志。 |

---

## 快速开始

### 1. 准备环境

- Python 3.10+（pandas/ta/openai 等需要较新的解释器）
- OKX API Key（只读 + 交易权限）
- DeepSeek/OpenAI/Qwen 等任一兼容 OpenAI 接口的 LLM Key
- Telegram Bot Token（可选，用于推送）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 `.env`

按模块抄写/修改，未用到的字段可留空。

```ini
# ---- OKX Account ----
OKX_API_KEY=xxx
OKX_API_SECRET=xxx
OKX_PASSPHRASE=xxx
OKX_BASE_URL=https://www.okx.com
OKX_TD_MODE=          ; cash / cross / isolated，空则智能推断
OKX_FORCE_POS_SIDE=   ; 1=始终携带 posSide，0=永不携带，空=根据账户配置
HTTP_TIMEOUT=10
HTTP_PROXY=

# ---- AI Provider ----
AI_PROVIDER=deepseek   ; deepseek/openai/azure_openai/qwen/moonshot/grok
DEEPSEEK_API_KEY=xxx
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# ---- Strategy / Runtime ----
BALANCE_USAGE_RATIO=0.7
DEFAULT_LEVERAGE=3
DEFAULT_TAKE_PROFIT_PCT=0.35   ; 0.35=+35%，止损同理
DEFAULT_STOP_LOSS_PCT=0.2
RUN_INTERVAL_MINUTES=5
DEFAULT_MAX_POSITION=0.002
FEATURE_LIMIT=150
LOG_DIR=logs
WATCHLIST_MODE=mixed            ; manual/auto/mixed
AUTO_WATCHLIST_SIZE=5
AUTO_WATCHLIST_TOP_N=10
AUTO_WATCHLIST_REFRESH_HOURS=24
AUTO_WATCHLIST_CACHE=data/auto_watchlist.json
AUTO_WATCHLIST_TIMEFRAME=5m
AUTO_WATCHLIST_HIGHER_TIMEFRAMES=15m,1H

# ---- Notification ----
NOTIFY_ENABLED=false
NOTIFY_LEVEL=critical          ; critical / orders / all
NOTIFY_COOLDOWN_SECONDS=600
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_API_URL=https://api.telegram.org
```

### 3. 启动

```bash
python main.py
```

启动过程会：

1. 展示 Rich LOGO → 打印核心配置 → 逐项加载引擎模块；
2. `WatchlistManager` 获取监控列表（手动/自动/混合）；
3. 为每个合约并发执行 `TradingEngine.run_once`，输出分析结果、信号、执行计划；
4. 每 `RUN_INTERVAL_MINUTES` 分钟复用线程池循环一次（`schedule`）。

> **Dry Run**：`main.py` 中 `DRY_RUN = False`，若需仿真可切换为 `True`（仍会计算信号但不会下单）。

### 4. 停止与日志

按 `Ctrl + C` 触发 `KeyboardInterrupt`，线程池与 WebSocket 会在 `finally` 中优雅关闭。运行日志默认写入 `LOG_DIR/runtime-*.log`。

---

## Watchlist 体系

### 手动模式 (`WATCHLIST_MODE=manual`)

编辑 `watchlist.json`：

```json
[
  {
    "inst_id": "BTC-USDT-SWAP",
    "timeframe": "5m",
    "higher_timeframes": ["15m", "1H", "4H"],
    "max_position": 0.003,
    "protection": {
      "take_profit": {"mode": "percent", "value": 0.4},
      "stop_loss": {"mode": "atr", "value": 1.8}
    }
  }
]
```

字段说明：

- `inst_id`：OKX 合约 ID，推荐 `*-USDT-SWAP` 永续。
- `timeframe`：基础周期（如 `5m`、`15m`）；多周期会自动半截历史长度。
- `higher_timeframes`：tuple/list/字符串（`,` 分隔），用于趋势/波动判定。
- `max_position`：单次信号允许的最大标的数量（基础值，之后会被资金+波动二次裁剪）。
- `protection`：覆盖全局默认的止盈/止损设置，可指定 `mode=percent/price/atr`。

### 止盈止损方案

- **触发行权**：策略输出的保护位统一归一到 `core.models.ProtectionTarget`，当 `mode=percent` 时，仅提供 `trigger_ratio`，交由执行层转成 OKX 文档所述的 `tpTriggerRatio/slTriggerRatio`（参见 [POST /api/v5/trade/place-order](https://www.okx.com/docs-v5/zh/#rest-api-trade-place-order) 中 `attachAlgoOrds` 参数说明），并强制 `order_type=market`，保证触发后直接以市价平仓。
- **ATR/Price**：`mode=atr/price` 只提供具体价位，执行层转成 `tpTriggerPx/slTriggerPx`，若配合限价委托则会将 `order_px` 带入 `tpOrdPx/slOrdPx`，否则下发 `-1` 市价。触发价类型默认 `last`，可在 watchlist 覆盖。
- **执行流程**：`core/execution.ExecutionEngine._build_attach_algo_orders` 会优先写入比例触发字段，且附带 `tpOrdKind/slOrdKind`，符合同一订单仅允许单向止盈止损的官方限制。一旦 `trigger_ratio/trigger_px` 命中，OKX 会立即创建 reduce-only 委托，从而实现“达到比例立即平仓”的需求。

### 自动模式 (`WATCHLIST_MODE=auto`)

`core/auto_watchlist.py` 会：

1. 调 OKX `GET /api/v5/market/tickers?instType=SWAP`，按 `volCcy24h` 排序；
2. 读取账户可用资金 → 根据 `BALANCE_USAGE_RATIO × DEFAULT_LEVERAGE` 计算最大可承受名义；
3. 按合约最小张数、合约面值、标价折算最小下单名义，过滤掉资金不足的品种；
4. 取前 `AUTO_WATCHLIST_SIZE` 个写入 `AUTO_WATCHLIST_CACHE` 并返回；
5. 缓存过期（`AUTO_WATCHLIST_REFRESH_HOURS`）或缓存缺失时才重新抓取。

### 混合模式 (`WATCHLIST_MODE=mixed`)

优先返回手动条目，再在自动列表里追加没有重名的合约。可用于「核心标的手动维护 + 补仓热度币」的场景。

---

## 策略 & 风控流水线

| 阶段 | 涉及模块 | 关键逻辑 |
| --- | --- | --- |
| 行情采集 | `core/data_utils.py`, `core/market_stream.py`, `core/data_pipeline.py` | REST/WebSocket K 线写入 Pandas，生成 RSI/EMA/MACD/ATR/布林/returns。盘口深度、成交、资金费率、持仓量并行采集并转换成易读文本。 |
| LLM 分析 | `core/analysis.py` | Build prompt（行情摘要 + 盘口 + 历史胜率 + 操作指引），批量调用 OpenAI 兼容接口，解析 JSON，磁盘缓存最后 64 个请求，写决策日志。 |
| 策略融合 | `core/strategy.py` | - Objective signals：RSI/EMA/MACD/Bollinger 多条件给出 buy/sell/hold + 置信度<br>- Higher timeframe bias：多周期趋势投票<br>- LLMInterpreter：严格 JSON → fallback 关键字<br>- SignalFusion：客观信号 + LLM 观点加权决策<br>- Liquidity/volatility/LLM 风险文本 → NOTE<br>- PositionSizer (`core/positioning.py`) 按置信度、ATR、账户权益/可用资金动态 sizing，附带 ATR/百分比止盈止损。 |
| 风控层 | `core/risk.py` | - 账户层：交易所风控标志、可用资金占比<br>- 品种层：成交量不足、近期波动超阈值、LLM 风险提示<br>- 信号层：多周期方向冲突 → 直接 HOLD，并把原因拼入 `TradeSignal.reason`。 |
| 执行层 | `core/execution.py` | - OKX instruments 缓存合约规格；自动折算 underlying ↔ contracts<br>- 根据 ATR/价格估计滑点，0.01 内 + 高置信使用限价单减少冲击<br>- 提前判定最小张数/最小下单不满足时抬升或阻断<br>- 构造 `attachAlgoOrds` 添加止盈止损。 |
| 账户评估 | `core/performance.py` | 后台线程每 15 min 刷新最近 7 日成交，统计 P/L、胜率、手续费、样本数，并在控制台/通知中展示。 |
| 通知/展示 | `core/notifications.py`, `main.py` | Rich 控制台面板（账户、行情摘要、LLM 文本、信号、执行计划、订单回执），Telegram 冷却策略（事件类型 × inst_id 键值对）。 |

---

## 运行时产物与缓存

| 文件 | 用途 |
| --- | --- |
| `logs/runtime-*.log` | Loguru 滚动日志（默认保留 7 天）。 |
| `logs/llm-cache.json` | 最近 64 个 LLM 返回缓存（命中则跳过请求，降低成本）。 |
| `logs/llm-decisions.jsonl` | 每次决策记录（信号、LLM 观点、收盘价），用于 `build_performance_hint`。 |
| `data/perf_cache.json` | `PerformanceTracker` 缓存，存储胜率/PnL。 |
| `data/auto_watchlist.json` | 自动 watchlist 缓存（含更新时间 + entries）。 |
| `watchlist.json` | 手动监控列表（热加载，文件修改后下轮生效）。 |

> 这些文件都可安全删除，程序会在需要时重新生成。

---

## 常见运维动作

1. **切换 AI provider**：修改 `.env` 中 `AI_PROVIDER` 及对应 API Key/Model/Base URL，重启即可，LLM 缓存会在新 provider 生效后刷新。
2. **Dry-Run 仿真**：`main.py` → 将 `DRY_RUN = True`，或在 `TradingEngine.run_once(... dry_run=True)` 方式中覆写。
3. **扩充指标/特征**：在 `core/data_utils.py` 添加自定义列，再在 `core/strategy.py` 消费；`build_market_summary` 会自动纳入文本描述。
4. **新增通知渠道**：扩展 `core/notifications.py`，让 `build_notifier` 返回自定义类，然后在 `main.py` 中按需 `send_notification`。
5. **接管 watchlist**：`WATCHLIST_MODE=manual` + Git 管理 `watchlist.json`；自动模式下可通过 `.env` 调整 `AUTO_WATCHLIST_*`。
6. **限制资金/杠杆**：通过 `.env` 中 `BALANCE_USAGE_RATIO`、`DEFAULT_LEVERAGE`、`DEFAULT_MAX_POSITION` 控制上限，并结合 watchlist 的 `max_position` 精细调节。
7. **手动触发一轮扫描**：运行 `python main.py`，待首轮执行完毕后 `Ctrl+C` 即可；若已在运行，可向控制台输入 `y` 通过启动确认。

---

## 常见问题 / FAQ

| 问题 | 处理方式 |
| --- | --- |
| **LLM 返回非 JSON 或 action 不合法** | `LLMInterpreter` 会自动降级为关键字/置信度提取，但建议在日志中检查 response，必要时调整提示词或更换模型。 |
| **订单被阻断** | 查看控制台的执行计划/执行反馈面板：可能是资金不足、最小下单限制、滑点超阈值或 RiskManager 拦截。 |
| **自动 watchlist 为空** | 账户可用资金 × 杠杆不足以覆盖任何候选合约的最小名义。调高 `BALANCE_USAGE_RATIO`/`DEFAULT_LEVERAGE` 或向账户划转资金。 |
| **WebSocket 无法建立** | `core/market_stream.py` 会捕获异常并回退 REST，只要安装 `websocket-client` 即可。若网络屏蔽 8443 端口，需配置代理 (`HTTP_PROXY`)。 |
| **性能统计始终为空** | 账户近 7 天无成交、API Key 无读成交权限或所在账户类型不支持 `get_fills`。可调用 `PerformanceTracker.get_snapshot_for_days(1)` 检查。 |
| **通知频率太高** | `NOTIFY_LEVEL=critical` 仅推失败/阻断；`orders` 包含成功订单；`NOTIFY_COOLDOWN_SECONDS` 控制事件冷却。 |
| **运行一段时间后占用高** | `ThreadPoolExecutor` 默认 worker≤8；定时任务常驻线程为 schedule + WebSocket + LLM 批处理，若不需要 WebSocket 可在 `main.py` 注释确保仅使用 REST。 |

---

## 安全提示

- 本仓库为示例架构，请在仿真环境中充分回测、复核风控逻辑后再投入实盘。
- 勿在公共仓库提交 `.env`、`logs`、`data` 等包含敏感信息的文件。
- 下单相关代码（`core/execution.py`）未包含「撤单/平仓逻辑」，如需双向操作请自行扩展。

---

祝交易顺利，记得「左舷火力太弱，让我们荡起双桨」之前先确认风控已就绪。🛡️🚀
