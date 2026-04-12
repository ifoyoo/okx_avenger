# OKX Avenger

操他妈的 OKX，上次害我亏了10U，所以这是一个面向 OKX 合约复仇的轻量自动交易程序，我期待再次爆仓，娱乐玩具勿当真。

当前实现重点：
- 手动 `watchlist.json`
- 单次运行 / 循环运行
- 内置信号、风控、止盈止损
- Telegram 通知
- 支持 `--dry-run`

## 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 最小配置

在项目根目录创建 `.env`：

```ini
OKX_API_KEY=xxx
OKX_API_SECRET=xxx
OKX_PASSPHRASE=xxx
OKX_TD_MODE=isolated

BALANCE_USAGE_RATIO=0.5
FEATURE_LIMIT=180
DEFAULT_LEVERAGE=10
DEFAULT_TAKE_PROFIT_PCT=0.06
DEFAULT_STOP_LOSS_PCT=0.03

NOTIFY_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
NOTIFY_LEVEL=orders
```

可选能力：
- 新闻：`NEWS_*`、`COINGECKO_*`
- LLM：`LLM_*`

不配也能运行。

## 3. Watchlist

编辑 `watchlist.json`：

```json
[
  "BTC-USDT-SWAP"
]
```

## 4. 运行

先检查配置：

```bash
./okx config-check
```

先跑模拟：

```bash
./okx once --dry-run
```

常驻循环：

```bash
./okx run --dry-run
```

查看账户和持仓：

```bash
./okx status
```

## 5. 实盘说明

- 去掉 `--dry-run` 才会真实下单。
- 资金过小会被最小下单量拦截。
- 杠杆要和 OKX 账户实际设置一致。
