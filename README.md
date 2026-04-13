# OKX Avenger (OKX 复仇者)

> Not here to look smart.  
> Here to stay alive long enough to fire the next order.
>
> Market does not care about your feelings.  
> Your stop loss should not care either.

操他妈的 OKX，上次害我亏了10U，所以这是一个面向 OKX 合约复仇的轻量自动交易程序，我期待再次爆仓，娱乐玩具勿当真。

当前版本的方向很明确：
- 手动 `watchlist.json`
- `once / run / status / backtest`
- 内置信号、风控、止盈止损
- Telegram 通知
- 支持 Gemini LLM 辅助判断
- 默认先用 `--dry-run`

## What It Is

这就是一套干脆的 OKX 合约运行框架：
- 盯住少数标的
- 拉数据
- 做判断
- 过风控
- 下单或拦截
- 把结果记下来并通知你

不吹神话，不卖梦想，只管把链路接结实。

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
```

## Structure

```text
okx_avenger/
├── README.md
├── requirements.txt
├── constraints.txt
├── .env
├── watchlist.json
├── okx                  # shell 入口
├── cli.py               # CLI 主入口
├── config/
│   ├── base.py          # .env 加载
│   └── settings.py      # 所有运行配置
├── cli_app/
│   ├── parser.py
│   ├── context.py
│   ├── runtime_*.py     # once / run / status
│   ├── backtest_*.py    # 回测与调参
│   └── strategy_*.py    # 策略开关与权重
├── core/
│   ├── analysis/        # 市场分析 / intel / llm brain
│   ├── client/          # OKX REST / WebSocket
│   ├── data/            # 特征 / 快照 / watchlist / performance
│   ├── engine/          # risk / execution / trading
│   ├── strategy/        # objective signals / fusion / sizing
│   └── protection.py    # 止盈止损配置解析
└── tests/               # 运行链路与核心模块测试
```

## Minimal Config

在根目录准备 `.env`：

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

NOTIFY_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
NOTIFY_LEVEL=orders

LLM_ENABLED=true
LLM_PROVIDER=openai_compatible
LLM_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY=
LLM_MODEL=gemini-2.5-flash
LLM_TIMEOUT_SECONDS=15
LLM_MAX_TOKENS=4096
```

## Watchlist

`watchlist.json` 现在默认就是最小实战形态：

```json
[
  "BTC-USDT-SWAP"
]
```

你当然可以加 `ETH-USDT-SWAP`，但别一上来把 watchlist 写成垃圾场。

## Run

先检查配置：

```bash
./okx config-check
```

如果你要重装环境，继续用这一条，不要裸装：

```bash
pip install -r requirements.txt -c constraints.txt
```

先跑模拟：

```bash
./okx once --dry-run
./okx run --dry-run
```

看账户和持仓：

```bash
./okx status
```

部署到 VPS 并一键更新：

```bash
./scripts/deploy_netcup.sh
./scripts/deploy_netcup.sh --sync-env --sync-watchlist
```

如果你已经在 VPS 上，只想更新代码并重启服务：

```bash
cd /root/apps/okx_avenger
./scripts/update_vps.sh
```

回测：

```bash
./okx backtest run --inst BTC-USDT-SWAP --timeframe 5m --limit 800
./okx backtest report
```

## Notes

- 去掉 `--dry-run` 才会真实下单。
- 资金太小，系统会因为最小下单量直接拦截。
- 杠杆要和 OKX 账户真实设置一致。
- LLM 只该辅助，不该替你发疯。
- Watchlist 少一点，归因才清楚。

## Attitude

这不是圣杯。
这不是财富自由按钮。
这是一套尽量把数据、风控、执行和通知接干净的 OKX 合约运行框架。

想活久一点，就先尊重仓位、尊重止损、尊重现实。

上面是装逼的，我很快会爆仓。

狗头狗头。
