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

BALANCE_USAGE_RATIO=0.6
DEFAULT_MAX_POSITION=0.02
FEATURE_LIMIT=180
DEFAULT_LEVERAGE=5
DEFAULT_TAKE_PROFIT_UPL_RATIO=0.20
DEFAULT_STOP_LOSS_UPL_RATIO=0.10
RISK_DAILY_LOSS_LIMIT_PCT=0.02
RISK_CONSECUTIVE_LOSS_LIMIT=3
RISK_CONSECUTIVE_COOLDOWN_MINUTES=360
EXECUTION_PENDING_ORDER_TTL_MINUTES=45
EXECUTION_ALLOW_SAME_DIRECTION_SCALE_IN=true
EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER=1.35

NOTIFY_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
NOTIFY_LEVEL=critical

LLM_ENABLED=true
LLM_PROVIDER=openai_compatible
LLM_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY=
LLM_MODEL=gemini-2.5-flash
LLM_TIMEOUT_SECONDS=15
LLM_MAX_TOKENS=4096
```

`DEFAULT_TAKE_PROFIT_UPL_RATIO` / `DEFAULT_STOP_LOSS_UPL_RATIO` 现在使用 OKX 持仓收益率语义，不是价格涨跌幅。
- `0.20` 表示持仓收益率到 `+20%` 平仓
- `0.10` 表示持仓收益率到 `-10%` 平仓
- 运行时会按当前杠杆换算成交易所触发价
- Telegram 现在只推送异常、阻断、下单失败，不再播报成功下单
- 同标的 live 未成交挂单超过 `EXECUTION_PENDING_ORDER_TTL_MINUTES=45` 后会先撤单，但本轮仍阻塞，下一轮再重新评估
- 开启 `EXECUTION_ALLOW_SAME_DIRECTION_SCALE_IN=true` 后，允许同方向加仓；`EXECUTION_SAME_DIRECTION_SCALE_IN_MULTIPLIER=3.0` 表示同向总仓位最多放大到 `max_position` 的 3 倍

## Watchlist

`watchlist.json` 现在默认就是最小实战形态：

```json
[
  {
    "inst_id": "BTC-USDT-SWAP",
    "max_position": 0.03
  }
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
- 默认 TP/SL 看的不是价格百分比，而是 OKX `uplRatio`。
- LLM 只该辅助，不该替你发疯。
- Watchlist 少一点，归因才清楚。

## Attitude

这不是圣杯。
这不是财富自由按钮。
这是一套尽量把数据、风控、执行和通知接干净的 OKX 合约运行框架。

想活久一点，就先尊重仓位、尊重止损、尊重现实。

上面是装逼的，我很快会爆仓。

狗头狗头。
