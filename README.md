# OKX 量化交易引擎

> 结合 OKX 官方 Python SDK、WebSocket 行情、技术指标分析与严控执行链条的多周期自动化交易框架。

---

## 项目亮点

- **端到端自动化**：`./okx` / `python cli.py` 统一驱动 watchlist 扫描、策略/风控、执行/通知，并按 `RUN_INTERVAL_MINUTES` 进入循环模式。
- **多维行情输入**：`core/data/snapshot.py` 聚合 OKX REST + WebSocket 的 K 线、盘口、实时成交、资金费率、持仓量，转成可读摘要供策略使用。
- **智能市场分析**：`core/analysis/market.py` 基于技术指标和结构进行确定性分析，提供趋势强度、动量评分、风险因素识别。
- **客观指标融合**：`core/strategy/core.py` 将 RSI/EMA/MACD/Bollinger/ATR 等客观指标、市场分析、波动/流动性过滤及 PositionSizer 组合成可执行信号。
- **三层风控 + 精细执行**：`core/engine/risk.py`（账户/品种/信号）、`core/engine/execution.py`（合约规格、止盈止损附带、滑点控制）、`core/data/performance.py`（近期盈亏快照）闭环。
- **手动 watchlist**：运行标的完全由 `watchlist.json` 管理；字符串条目默认使用 `5m + 1H`，也支持按标的覆盖周期、仓位和情报别名。
- **可观测性完备**：Rich 控制台、Loguru 滚动日志、决策记录、`data/perf_cache.json` 绩效缓存、Telegram 冷却通知全可追溯。

---

## 系统架构

```text
┌────────────┐   ┌──────────────────────────────────────────────┐
│watchlist   │   │MarketDataStream + OKX REST (core/client/rest.py)  │
│watchlist.json│──▶ Kline/OrderBook/Trades/Funding/OI             │
└────┬───────┘   └───────────────┬──────────────────────────────┘
     │                           │
     │                  ┌────────▼────────┐
     │                  │Feature Builder  │ candles_to_dataframe +
     │                  │(core/data/features.py)│ indicators / volatility
     │                  └────────┬────────┘
     │                           │
┌────▼───────┐    ┌──────────────▼─────────────┐
│Watchlist   │    │MarketSnapshotCollector     │
│Manager     │    │+ build_market_summary      │
│(manual)    │    └──────────────┬─────────────┘
└────┬───────┘                   │ snapshot text
     │                           │
     │                    ┌──────▼──────┐ MarketAnalyzer
     │ signals            │市场分析     │ (core/analysis/market.py)
     │                    └──────┬──────┘
     │                           │ 分析结果 + summary + history
┌────▼───────┐           ┌───────▼────────┐
│Strategy    │           │RiskManager      │
│(objective +│──────────▶│+ PositionSizer  │
│analysis)   │           └───────┬────────┘
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
                          │Engine     │ notify, runtime loop
                          └───────────┘
```

---

## 目录导览

| 路径 | 说明 |
| --- | --- |
| `cli.py` / `okx` | 当前唯一受支持入口；`okx` 是 shell 包装，实际执行 `cli.py`。 |
| `config/` | `settings.py` 定义 Pydantic Settings（账户、策略、运行、通知），`.env` 自动加载。 |
| `core/client/rest.py` | 封装 OKX REST Account/Trade/Market/Public API 并做错误包装。 |
| `core/data/features.py` | OKX K 线 → Pandas + RSI/EMA/MACD/ATR/布林/收益率/波动指标。 |
| `core/data/snapshot.py` | 行情摘要 + 盘口/成交/衍生品快照 + 多周期描述。 |
| `core/analysis/market.py` | 市场分析器，基于技术指标和结构进行确定性分析。 |
| `core/strategy/core.py` | 客观信号、分析解析、信号融合、动态风控提示、保护价生成。 |
| `core/strategy/positioning.py` | PositionSizer，基于权益/可用资金/ATR/信号置信度调仓。 |
| `core/engine/risk.py` | 账户风控（可用资金占比/交易所风控）、流动性、波动、趋势冲突。 |
| `core/engine/execution.py` | 合约规格缓存、张数折算、滑点评估、TP/SL 附单、执行报告。 |
| `core/data/performance.py` | 最近 N 天成交抓取、盈亏/胜率/手续费统计缓存。 |
| `core/data/watchlist_loader.py` | 手动 watchlist 解析、默认周期补全与运行期热加载。 |
| `core/client/stream.py` | WebSocket 缓存 K 线/盘口/成交，REST 不足时自动回退。 |
| `core/utils/notifications.py` | Telegram 冷却推送。 |
| `data/` | `perf_cache.json` 等运行时缓存。 |
| `logs/` | 滚动日志、决策记录、运行日志。 |

---

## 快速开始

### 1. 准备环境

- Python 3.10+（pandas/ta 等需要较新的解释器）
- OKX API Key（只读 + 交易权限）
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

# ---- Strategy / Runtime ----
BALANCE_USAGE_RATIO=0.5
DEFAULT_LEVERAGE=3
DEFAULT_TAKE_PROFIT_PCT=0.06   ; 0.06=+6%，止损同理
DEFAULT_STOP_LOSS_PCT=0.03
STRATEGY_SIGNALS_ENABLED=all   ; all 或逗号列表，如 bull_trend,ma_golden_cross,volume_breakout
STRATEGY_SIGNAL_WEIGHTS=        ; 形如 bull_trend=1.1,box_oscillation=0.8
RUN_INTERVAL_MINUTES=5
DEFAULT_MAX_POSITION=0.002
FEATURE_LIMIT=180
LOG_DIR=logs
# watchlist 直接维护在 watchlist.json

# ---- Notification ----
NOTIFY_ENABLED=false
NOTIFY_LEVEL=critical          ; critical / orders / all
NOTIFY_COOLDOWN_SECONDS=600
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_API_URL=https://api.telegram.org

# ---- LLM Brain (Optional) ----
LLM_ENABLED=false
LLM_PROVIDER=openai_compatible
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=8
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=320

# ---- News / Sentiment Intel (Optional) ----
NEWS_ENABLED=false
NEWS_PROVIDER=newsapi
NEWS_PROVIDERS=coingecko,newsapi
NEWS_API_BASE=https://newsapi.org/v2/everything
NEWS_API_KEY=
NEWS_TIMEOUT_SECONDS=6
NEWS_LIMIT=10
NEWS_WINDOW_HOURS=24
SENTIMENT_ENABLED=true
NEWS_SYMBOL_ALIASES=
NEWS_COIN_IDS=
COINGECKO_API_BASE=https://pro-api.coingecko.com/api/v3
COINGECKO_API_KEY=
COINGECKO_NEWS_LANGUAGE=en
COINGECKO_NEWS_TYPE=news
```

### 3. 启动

```bash
./okx once --dry-run
```

启动过程会：

1. 读取 `.env` 与 `watchlist.json`，组装运行时依赖；
2. `WatchlistManager` 获取监控列表；
3. 为每个合约执行 `TradingEngine.run_once`，输出分析结果、信号、执行计划；
4. 若使用 `./okx run`，按 `RUN_INTERVAL_MINUTES` 持续循环。

> **Dry Run**：使用 `./okx once --dry-run` 或 `./okx run --dry-run`，会完整计算信号但不实际下单。

### 3.1 推荐：简洁 CLI（无交互启动）

```bash
# 执行一轮（按 watchlist）
./okx once --dry-run

# 只跑单一标的
./okx once --inst BTC-USDT-SWAP --timeframe 5m --higher-timeframes 1H --dry-run

# 常驻循环（默认读取 RUN_INTERVAL_MINUTES）
./okx run

# 查看账户/持仓/watchlist
./okx status

# 查看策略开关与权重
./okx strategies list
./okx strategies enable bull_trend ma_golden_cross
./okx strategies disable box_oscillation
./okx strategies set-weight bull_trend 1.20
./okx strategies reset-weight bull_trend
./okx strategies clear-weights

# 配置检查（可选 API 连通性）
./okx config-check --api-check

# 快速回测
./okx backtest run --inst BTC-USDT-SWAP --timeframe 5m --limit 800 --warmup 120
./okx backtest report

# 基于回测推荐策略权重（预览 / 应用）
./okx backtest tune --inst BTC-USDT-SWAP --timeframe 5m --limit 800
./okx backtest tune --inst BTC-USDT-SWAP --timeframe 5m --limit 800 --apply
```

如果你希望在任意目录直接使用 `okx run`（不加 `./`），可把项目目录加入 `PATH`，或做软链：

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/okx" ~/.local/bin/okx
# 确保 ~/.local/bin 在 PATH 中
```

### 4. 停止与日志

按 `Ctrl + C` 触发 `KeyboardInterrupt`，线程池与 WebSocket 会在 `finally` 中优雅关闭。运行日志默认写入 `LOG_DIR/runtime-*.log`。

---

## Watchlist 体系

Watchlist 现在只保留手动模式，直接维护 `watchlist.json`：

编辑 `watchlist.json`：

```json
[
  "BTC-USDT-SWAP",
  "ETH-USDT-SWAP"
]
```

也支持在少数特殊标的上使用对象覆盖默认值：

```json
[
  "BTC-USDT-SWAP",
  {
    "inst_id": "ETH-USDT-SWAP",
    "higher_timeframes": ["4H"]
  }
]
```

字段说明：

- `inst_id`：OKX 合约 ID，推荐 `*-USDT-SWAP` 永续。
- `timeframe`：可选，默认 `5m`；只有特殊标的才建议覆盖。
- `higher_timeframes`：可选，默认 `1H`；用于趋势/波动判定。
- `max_position`：单次信号允许的最大标的数量（基础值，之后会被资金+波动二次裁剪）。
- `protection`：覆盖全局默认的止盈/止损设置，可指定 `mode=percent/price/atr`。

### 止盈止损方案

- **统一契约**：`watchlist.json` / 默认配置里写的是 `ProtectionRule`，`TradeSignal.protection` 也只保留规则意图；真正的触发位由 `core.protection.resolve_trade_protection()` 在执行层和回测层按入场价统一解析，不再各自拼一套 TP/SL 语义。
- **支持模式**：`mode=percent/price/atr/rr`。其中 `ratio/pct/percentage` 会自动归一到 `percent`；`rr` 只用于止盈，表示以已解析止损距离为 `1R`，例如 `stop_loss=1%` + `take_profit=2R` 会得到 `2%` 止盈。
- **Percent**：解析后同时保留 `trigger_ratio` 和 `trigger_px`。执行层会优先下发 OKX 的 `tpTriggerRatio/slTriggerRatio`，让百分比保护围绕实际成交价工作；回测层则消费同一个规则解析出的绝对价格。
- **ATR / Price / RR**：这些模式解析成具体价位，执行层转成 `tpTriggerPx/slTriggerPx`；若 `order_type=limit` 则会带入 `tpOrdPx/slOrdPx`，否则下发 `-1` 市价。触发价类型默认 `last`，可在 watchlist 覆盖。
- **回测语义**：回测开仓后会在同一根执行 bar 内检查 TP/SL；若同一根 K 线同时触发止盈和止损，默认按保守原则先记止损，从而避免把未知的 intrabar 顺序高估成收益。

---

## 策略 & 风控流水线

| 阶段 | 涉及模块 | 关键逻辑 |
| --- | --- | --- |
| 行情采集 | `core/data/features.py`, `core/client/stream.py`, `core/data/snapshot.py` | REST/WebSocket K 线写入 Pandas，生成 RSI/EMA/MACD/ATR/布林/returns。盘口深度、成交、资金费率、持仓量并行采集并转换成易读文本。 |
| 市场分析 | `core/analysis/market.py` | 基于技术指标和结构进行确定性分析，计算趋势强度、动量评分、识别支撑/阻力位和风险因素，生成结构化分析文本。 |
| 新闻/舆情情报（可选） | `core/analysis/intel.py` | 当 `NEWS_ENABLED=true` 时拉取新闻，进行去重、关键词风险标注与情绪打分（确定性预处理），输出 `sentiment_score/risk_tags/headlines` 供 LLM 与策略参考。 |
| LLM 分析大脑（可选） | `core/analysis/llm_brain.py` | 当 `LLM_ENABLED=true` 时调用 OpenAI 兼容接口输出结构化观点（`action/confidence/risk/invalid_conditions`），仅参与融合，不直接下单；超时/失败自动回退确定性分析。 |
| 策略融合 | `core/strategy/core.py` | - Objective signals：RSI/EMA/MACD/Bollinger 多条件给出 buy/sell/hold + 置信度<br>- Higher timeframe bias：多周期趋势投票<br>- AnalysisInterpreter：解析市场分析结果<br>- SignalFusion：客观信号 + 市场分析加权决策<br>- Liquidity/volatility/风险文本 → NOTE<br>- PositionSizer (`core/strategy/positioning.py`) 按置信度、ATR、账户权益/可用资金动态 sizing，附带 ATR/百分比止盈止损。 |
| 风控层 | `core/engine/risk.py` | - 账户层：交易所风控标志、可用资金占比<br>- 品种层：成交量不足、近期波动超阈值、风险提示<br>- 信号层：多周期方向冲突 → 直接 HOLD，并把原因拼入 `TradeSignal.reason`。 |
| 执行层 | `core/engine/execution.py` | - OKX instruments 缓存合约规格；自动折算 underlying ↔ contracts<br>- 根据 ATR/价格估计滑点，0.01 内 + 高置信使用限价单减少冲击<br>- 提前判定最小张数/最小下单不满足时抬升或阻断<br>- 构造 `attachAlgoOrds` 添加止盈止损。 |
| 账户评估 | `core/data/performance.py` | 后台线程每 15 min 刷新最近 7 日成交，统计 P/L、胜率、手续费、样本数，并在控制台/通知中展示。 |
| 通知/展示 | `core/utils/notifications.py`, `cli_app/runtime_*` | CLI 日志输出、状态视图、heartbeat 与 Telegram 冷却策略（事件类型 × inst_id 键值对）。 |

---

## 运行时产物与缓存

| 文件 | 用途 |
| --- | --- |
| `logs/runtime-*.log` | Loguru 滚动日志（默认保留 7 天）。 |
| `data/perf_cache.json` | `PerformanceTracker` 缓存，存储胜率/PnL。 |
| `watchlist.json` | 手动监控列表（热加载，文件修改后下轮生效）。 |

> 这些文件都可安全删除，程序会在需要时重新生成。

---

## 常见运维动作

1. **Dry-Run 仿真**：使用 `./okx once --dry-run` 或 `./okx run --dry-run`。
2. **扩充指标/特征**：在 `core/data/features.py` 添加自定义列，再在 `core/strategy/core.py` 消费；`build_market_summary` 会自动纳入文本描述。
3. **新增通知渠道**：扩展 `core/utils/notifications.py`，并在 CLI workflow 中接入新的通知调用点。
4. **接管 watchlist**：直接用 Git 管理 `watchlist.json`。
5. **限制资金/杠杆**：通过 `.env` 中 `BALANCE_USAGE_RATIO`、`DEFAULT_LEVERAGE`、`DEFAULT_MAX_POSITION` 控制上限，并结合 watchlist 的 `max_position` 精细调节。
6. **手动触发一轮扫描**：运行 `./okx once`；若只想验证链路，优先使用 `./okx once --dry-run`。

---

## 常见问题 / FAQ

| 问题 | 处理方式 |
| --- | --- |
| **订单被阻断** | 查看控制台的执行计划/执行反馈面板：可能是资金不足、最小下单限制、滑点超阈值或 RiskManager 拦截。 |
| **WebSocket 无法建立** | `core/client/stream.py` 会捕获异常并回退 REST，只要安装 `websocket-client` 即可。若网络屏蔽 8443 端口，需配置代理 (`HTTP_PROXY`)。 |
| **性能统计始终为空** | 账户近 7 天无成交、API Key 无读成交权限或所在账户类型不支持 `get_fills`。可调用 `PerformanceTracker.get_snapshot_for_days(1)` 检查。 |
| **通知频率太高** | `NOTIFY_LEVEL=critical` 仅推失败/阻断；`orders` 包含成功订单；`NOTIFY_COOLDOWN_SECONDS` 控制事件冷却。 |
| **运行一段时间后占用高** | 优先检查 watchlist 大小、日志量和 WebSocket/REST 使用情况；当前常驻入口是 `./okx run`，不再存在旧 `main.py` 调度路径。 |

---

## 安全提示

- 本仓库为示例架构，请在仿真环境中充分回测、复核风控逻辑后再投入实盘。
- 勿在公共仓库提交 `.env`、`logs`、`data` 等包含敏感信息的文件。
- 下单相关代码（`core/engine/execution.py`）未包含「撤单/平仓逻辑」，如需双向操作请自行扩展。

---

祝交易顺利，记得「左舷火力太弱，让我们荡起双桨」之前先确认风控已就绪。🛡️🚀
