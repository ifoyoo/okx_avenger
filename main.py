"""OKX 主入口：运行完整交易引擎."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import schedule
from loguru import logger
from rich import box
from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import RuntimeSettings
from config.settings import get_settings
from core.client import MarketDataStream, OKXClient
from core.data.performance import PerformanceTracker
from core.data.watchlist_loader import WatchlistManager, load_watchlist
from core.engine.execution import ExecutionPlan, ExecutionReport
from core.engine.protection import ProtectionMonitor, ProtectionThresholds
from core.engine.trading import TradingEngine
from core.models import ProtectionTarget, TradeSignal
from core.strategy.core import Strategy
from core.analysis import MarketAnalyzer
from core.utils.notifications import Notifier, build_notifier

ACTION_EMOJI = {
    "buy": "🟢",
    "sell": "🔴",
    "hold": "⚪",
}
ERROR_HINTS = {
    "51008": "保证金不足，请补充 USDT 或降低仓位。",
    "51004": "当前持仓方向受限，检查账户持仓模式。",
    "58150": "触发风控限制，稍后重试或联系 OKX 支持。",
}

RUN_INTERVAL_MINUTES = 5
DEFAULT_MAX_POSITION = 0.002
DRY_RUN = False
FEATURE_LIMIT = 150
LOG_DIR: Optional[Path] = None


def _manual_watchlist_size() -> int:
    try:
        return len(load_watchlist())
    except Exception:
        return 0


def _estimate_worker_count(runtime_settings: RuntimeSettings) -> int:
    auto_target = int(getattr(runtime_settings, "auto_watchlist_size", 0) or 0)
    mode = (runtime_settings.watchlist_mode or "manual").strip().lower()
    manual_size = _manual_watchlist_size()
    if mode == "manual":
        desired = manual_size or auto_target or 1
    elif mode == "auto":
        desired = auto_target or manual_size or 1
    else:
        desired = (manual_size or 0) + (auto_target or 0)
    return max(1, min(8, desired))


def _derive_batch_config(worker_count: int) -> Tuple[int, float]:
    if worker_count <= 2:
        return 2, 0.06
    if worker_count <= 4:
        return 4, 0.1
    if worker_count <= 6:
        return 6, 0.12
    return 8, 0.15


def _watchlist_info_text(runtime_settings: RuntimeSettings) -> str:
    raw_mode = (runtime_settings.watchlist_mode or "manual").strip()
    mode = raw_mode.upper()
    auto_target = int(getattr(runtime_settings, "auto_watchlist_size", 0) or 0)
    manual_size = _manual_watchlist_size()
    mode_lower = raw_mode.lower()
    if mode_lower == "manual":
        count = manual_size or 0
    elif mode_lower == "auto":
        count = auto_target or 0
    else:
        count = (manual_size or 0) + (auto_target or 0)
    return f"{mode} · 合约数量 {count}"


def render_section(console: Console, title: str, style: str = "dim") -> None:
    text = Text(title, justify="center", style=style)
    section_panel = Panel(
        Align.center(text),
        border_style=style,
        padding=(0, 2),
        expand=True,
    )
    console.print(section_panel)


def print_centered(console: Console, renderable: Any) -> None:
    console.print(Align.center(renderable))


def render_info_panel(
    console: Console,
    title: str,
    content: Any,
    style: str = "cyan",
) -> None:
    if isinstance(content, str):
        body = Text(content)
    else:
        body = content
    console.print(
        Panel(
            body,
            title=title,
            border_style=style,
            padding=(1, 2),
            expand=True,
        )
    )


def format_account_context(
    account_snapshot: Optional[Dict[str, float]],
    perf_stats: Optional[Dict[str, Any]],
    daily_stats: Optional[Dict[str, Any]],
) -> str:
    parts = []
    if account_snapshot:
        equity = account_snapshot.get("equity")
        available = account_snapshot.get("available")
        if equity is not None:
            parts.append(f"总权益 {equity:.2f} USD")
        if available is not None and equity:
            parts.append(f"可用 {available:.2f} USD ({available / equity * 100:.0f}%)")
    if perf_stats:
        sample = perf_stats.get("sample_count")
        pnl = perf_stats.get("total_pnl")
        win_rate = perf_stats.get("win_rate")
        if sample:
            parts.append(
                f"近{int(perf_stats.get('lookback_days', 0) or 0)}日 P/L {pnl or 0:+.2f} USDT "
                f"| 胜率 {win_rate * 100 if win_rate is not None else 0:.0f}% "
                f"| 样本 {sample}"
            )
    if daily_stats:
        sample = daily_stats.get("sample_count")
        pnl = daily_stats.get("total_pnl")
        if sample:
            win_rate = daily_stats.get("win_rate") or 0.0
            parts.append(
                f"当日 P/L {pnl or 0:+.2f} USDT | 胜率 {win_rate * 100:.0f}% | 样本 {sample}"
            )
    return "\n".join(parts) if parts else ""


def _should_notify_level(level: str, event_type: str) -> bool:
    normalized = (level or "critical").strip().lower()
    level_map = {
        "critical": {"failure", "blocked"},
        "orders": {"failure", "blocked", "success"},
        "all": {"failure", "blocked", "success", "info"},
    }
    allowed = level_map.get(normalized, level_map["critical"])
    return event_type in allowed


def _format_line_html(line: str) -> str:
    if not line:
        return ""
    full_width_colon = "："
    label = None
    value = None
    if full_width_colon in line:
        label, value = line.split(full_width_colon, 1)
        colon = full_width_colon
    elif ":" in line:
        label, value = line.split(":", 1)
        colon = ":"
    if label is not None:
        return f"<b>{escape(label)}{colon}</b> {escape(value)}"
    return escape(line)


def send_notification(
    notifier: Optional[Notifier],
    title: str,
    lines: List[str],
    account_snapshot: Optional[Dict[str, float]] = None,
    perf_stats: Optional[Dict[str, Any]] = None,
    daily_stats: Optional[Dict[str, Any]] = None,
    event_type: str = "info",
    inst_id: str = "",
    notify_level: str = "critical",
) -> None:
    if not notifier:
        return
    if not _should_notify_level(notify_level, event_type):
        return
    key = (event_type, inst_id or "")
    if hasattr(notifier, "should_send") and not notifier.should_send(key):
        return
    context = format_account_context(account_snapshot, perf_stats, daily_stats)
    bullet_lines = [f"• {_format_line_html(line)}" for line in lines if line]
    emoji_map = {"success": "✅", "failure": "❌", "blocked": "⚠️", "info": "ℹ️"}
    header = f"{emoji_map.get(event_type, '🔔')} <b><u>{escape(title)}</u></b>"
    message_parts = [header]
    if bullet_lines:
        message_parts.append("\n".join(bullet_lines))
    if context:
        context_html = escape(context)
        message_parts.append(f"<i>{context_html}</i>")
    message = "\n\n".join(message_parts)
    notifier.send(message, parse_mode="HTML")


def _minimal_launch(console: Console) -> None:
    """极简启动模式：无动画、无确认、快速启动."""
    settings = get_settings()

    # 构建核心信息
    version = f"v{getattr(settings.runtime, 'app_version', None) or 'unknown'}"
    watchlist_info = _watchlist_info_text(settings.runtime)
    analysis_mode = "技术分析 + 指标" if settings.strategy.enable_analysis else "纯指标"
    leverage = f"{settings.strategy.default_leverage}x"
    tp_sl = f"{settings.strategy.default_take_profit_pct * 100:.0f}% / {settings.strategy.default_stop_loss_pct * 100:.0f}%"

    # 单行紧凑显示
    info_text = (
        f"[bold cyan]OKX 交易引擎[/bold cyan] {version} | "
        f"[bold yellow]{watchlist_info}[/bold yellow] | "
        f"[bold magenta]{analysis_mode}[/bold magenta] | "
        f"杠杆 {leverage} | 止盈/止损 {tp_sl}"
    )

    console.print(Panel(
        Align.center(info_text),
        border_style="green",
        padding=(0, 2),
    ))
    console.print("[dim]按 Ctrl+C 随时终止[/dim]\n")


def _confirm_launch(console: Console) -> None:
    from time import perf_counter

    from rich.live import Live

    settings = get_settings()
    panel_width = 60
    o_lines = [
        " █████ ",
        "██   ██",
        "██   ██",
        "██   ██",
        " █████ ",
    ]
    k_lines = [
        "██  ██",
        "██ ██ ",
        "████  ",
        "██ ██ ",
        "██  ██",
    ]
    x_lines = [
        "██   ██",
        " ██ ██ ",
        "  ███  ",
        " ██ ██ ",
        "██   ██",
    ]
    logo_lines = [f"{o}  {k}  {x}" for o, k, x in zip(o_lines, k_lines, x_lines)]
    gradient = ["#39FF14", "#00FFC6", "#00E0FF", "#00A3FF", "#39FF14"]

    def build_gradient_logo(frame: int, signature_markup: str = "") -> Panel:
        logo = Text()
        for line in logo_lines:
            for idx, char in enumerate(line):
                color = gradient[(idx + frame) % len(gradient)]
                logo.append(char, style=f"bold {color}")
            logo.append("\n")
        block = logo
        if signature_markup:
            block.append("\n")
            block.append(Text.from_markup(signature_markup))
        return Align.center(
            Panel(
                Align.center(block, vertical="middle"),
                border_style="bright_cyan",
                padding=(1, 4),
                width=panel_width,
            )
        )

    author_text = getattr(settings.runtime, "app_author", "") or ""
    typed = ""
    extra_hold = 0.8
    hold_until: Optional[float] = None
    frame = 0
    with Live(
        build_gradient_logo(frame), console=console, refresh_per_second=18
    ) as live:
        while True:
            if len(typed) < len(author_text):
                typed += author_text[len(typed)]
                if len(typed) == len(author_text):
                    hold_until = perf_counter() + extra_hold
            frame += 1
            signature_markup = f"[bold cyan]{typed}[/]"
            live.update(build_gradient_logo(frame, signature_markup))
            time.sleep(0.08)
            if (
                len(typed) == len(author_text)
                and hold_until
                and perf_counter() >= hold_until
            ):
                break

    info_rows = [
        (
            "📦 当前版本",
            f"v{getattr(settings.runtime, 'app_version', None) or 'unknown'}",
        ),
        ("⏱️  启动时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        (
            "👀 监视模式",
            _watchlist_info_text(settings.runtime),
        ),
        ("⚖️  杠杆倍数", f"{settings.strategy.default_leverage}x"),
        (
            "💰 最大资金",
            f"可用资金的 {settings.strategy.balance_usage_ratio:.0%}",
        ),
        (
            "🤖 分析模式",
            "技术分析 + 指标" if settings.strategy.enable_analysis else "纯指标",
        ),
        (
            "🎯 止盈 / ⚠️ 止损",
            f"{settings.strategy.default_take_profit_pct * 100:.0f}% / {settings.strategy.default_stop_loss_pct * 100:.0f}%",
        ),
        ("💡 币圈交易友情提示", "遇到收 U 的养生馆就珍惜吧。"),
    ]
    info_table = Table(show_edge=False, box=None, padding=(0, 1))
    info_table.add_column(
        "关键配置", style="bold cyan", justify="center", header_style="bold"
    )
    info_table.add_column(
        "值", style="bold white", justify="center", header_style="bold"
    )

    for label, value in info_rows:
        info_table.add_row(label, value)
    panel = Panel(info_table, title="启动信息", border_style="cyan", width=panel_width)
    console.print(Align.center(panel))

    table = Table(show_edge=False, box=None, padding=(0, 1))
    table.add_column("模块", style="bold cyan", justify="center")
    table.add_column("说明", style="white", justify="center")
    table.add_column("状态", style="bold white", justify="center")
    steps = [
        ("⚙️  引擎模块", "加载核心依赖与运行环境"),
        ("🧠 策略模块", "初始化策略逻辑与市场分析"),
        ("🛡️  风控模块", "准备账户风控参数与资金快照"),
        ("🚀 执行模块", "连接 OKX 下单接口并校验"),
        ("💹 交易模块", "检查账户仓位、持仓模式与限制"),
        ("📈 监控模块", "刷新监控资产与自动候选列表"),
        ("📣 通知模块", "准备 Telegram 推送与冷却管理"),
    ]
    for name, desc in steps:
        table.add_row(name, desc, "[bold green]✔[/bold green]")
    console.print(
        Align.center(
            Panel(table, title="模块加载", border_style="cyan", width=panel_width)
        )
    )
    console.print(
        Align.center(
            Panel(
                "[bold green]OKX 交易引擎已就绪！左舷火力太弱，让我们荡起双桨！！！[/bold green]",
                border_style="green",
                width=panel_width,
            )
        )
    )
    while True:
        print_centered(
            console,
            "[bold yellow]请输入 y 继续启动程序，运行后按 Ctrl + C 随时终止：[/bold yellow]",
        )
        response = console.input("> ").strip().lower()
        if response == "y":
            break
        print_centered(console, "[yellow]仅输入 y 才能继续运行。[/yellow]")


def _configure_runtime(runtime_settings: RuntimeSettings) -> None:
    global RUN_INTERVAL_MINUTES, DEFAULT_MAX_POSITION, FEATURE_LIMIT, LOG_DIR
    RUN_INTERVAL_MINUTES = runtime_settings.run_interval_minutes
    DEFAULT_MAX_POSITION = runtime_settings.default_max_position
    FEATURE_LIMIT = runtime_settings.feature_limit
    LOG_DIR = Path(runtime_settings.log_dir)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        LOG_DIR / "runtime-{time}.log",
        rotation="1 day",
        retention="7 days",
        enqueue=True,
        level="INFO",
    )


def process_instrument(
    engine: TradingEngine,
    console: Console,
    item: Dict[str, Any],
    account_snapshot: Optional[Dict[str, float]] = None,
    perf_stats: Optional[Dict[str, Any]] = None,
    daily_stats: Optional[Dict[str, Any]] = None,
    notifier: Optional[Notifier] = None,
    notify_level: str = "critical",
    positions_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> None:
    inst_id = item["inst_id"]
    timeframe = item.get("timeframe", "5m")
    max_position = float(item.get("max_position", DEFAULT_MAX_POSITION))
    higher_timeframes: Tuple[str, ...] = tuple(item.get("higher_timeframes", ()))
    render_section(console, f"{inst_id} · {timeframe}", style="bold green")
    protection_overrides = item.get("protection")
    if protection_overrides is not None and not isinstance(protection_overrides, dict):
        protection_overrides = None
    try:
        result = engine.run_once(
            inst_id=inst_id,
            timeframe=timeframe,
            limit=FEATURE_LIMIT,
            dry_run=DRY_RUN,
            max_position=max_position,
            higher_timeframes=higher_timeframes,
            account_snapshot=account_snapshot,
            protection_overrides=protection_overrides,
            positions_snapshot=(
                positions_map.get(inst_id.upper()) if positions_map else None
            ),
            perf_stats=perf_stats,
            daily_stats=daily_stats,
        )
    except Exception as exc:  # pragma: no cover
        console.print(f"[red]执行 {inst_id} 失败: {exc}[/red]")
        return

    signal: TradeSignal = result["signal"]
    summary_text = result.get("analysis_summary")
    history_hint = result.get("history_hint")
    enable_analysis = engine.strategy_settings.enable_analysis

    if summary_text:
        render_info_panel(
            console, "行情摘要", Markdown(summary_text), style="bold cyan"
        )
    if history_hint:
        render_info_panel(
            console, "历史表现", Markdown(history_hint), style="bold cyan"
        )

    # 根据分析模式调整标题
    analysis_title = "市场分析" if enable_analysis else "市场分析（纯指标模式）"
    analysis_style = "bold magenta" if enable_analysis else "bold cyan"
    render_info_panel(
        console, analysis_title, Markdown(result["analysis"]), style=analysis_style
    )
    summary_line = (
        f"{result['signal'].action.value.upper()} @ {timeframe} "
        f"size={result['signal'].size:.6f} conf={result['signal'].confidence:.2f}"
    )
    render_info_panel(console, "策略信号概要", summary_line, style="bold yellow")
    display_signal(signal, console)
    render_info_panel(console, "信号解析", Markdown(signal.reason), style="bold green")
    execution_payload = result.get("execution") or {}
    execution_plan: Optional[ExecutionPlan] = execution_payload.get("plan")
    execution_report: Optional[ExecutionReport] = execution_payload.get("report")
    order_resp = result.get("order")
    if order_resp:
        data = order_resp.get("data") or []
        entry = data[0] if data else {}
        code = str(order_resp.get("code", ""))
        s_code = str(entry.get("sCode", ""))
        status_ok = code in ("0", "200") and s_code == "0"
        order_id = entry.get("ordId") or "-"
        action_label = f"{ACTION_EMOJI.get(signal.action.value, '➡️')} {signal.action.value.upper()}"
        base_lines = [
            f"合约：{inst_id} · {timeframe}",
            f"方向：{action_label}",
            f"信号尺寸：{signal.size:.6f} | 置信度：{signal.confidence:.2f}",
        ]
        if status_ok:
            avg_price = entry.get("avgPx") or entry.get("fillPx") or "-"
            qty = entry.get("sz") or entry.get("fillSz") or "-"
            logger.info(
                "Order success inst_id={} ord_id={} avg_px={} qty={} size={:.6f} conf={:.2f}",
                inst_id,
                order_id,
                avg_price,
                qty,
                signal.size,
                signal.confidence,
            )
            if notifier:
                lines = base_lines + [
                    f"订单ID：{order_id}",
                    f"成交均价：{avg_price}",
                    f"成交数量：{qty}",
                ]
                send_notification(
                    notifier,
                    "下单成功",
                    lines,
                    account_snapshot,
                    perf_stats,
                    daily_stats,
                    event_type="success",
                    inst_id=inst_id,
                    notify_level=notify_level,
                )
        else:
            err_msg = entry.get("sMsg") or order_resp.get("msg") or "未知错误"
            logger.warning(
                "Order failure inst_id={} ord_id={} code={} s_code={} reason={}",
                inst_id,
                order_id,
                code,
                s_code,
                err_msg,
            )
            if notifier:
                lines = base_lines + [
                    f"订单ID：{order_id}",
                    f"原因：{err_msg}",
                ]
                send_notification(
                    notifier,
                    "下单失败",
                    lines,
                    account_snapshot,
                    perf_stats,
                    daily_stats,
                    event_type="failure",
                    inst_id=inst_id,
                    notify_level=notify_level,
                )
    if execution_plan:
        display_execution_plan(execution_plan, console)
    if order_resp:
        display_order_result(order_resp, signal, console)
    elif execution_report and not execution_report.success:
        logger.warning(
            "Execution failure inst_id={} reason={} code={}",
            inst_id,
            execution_report.error or "未知错误",
            execution_report.code or "-",
        )
        display_execution_feedback(execution_report, console)
    elif execution_plan and execution_plan.blocked:
        logger.info(
            "Execution blocked inst_id={} reason={}",
            inst_id,
            execution_plan.block_reason or "无交易动作",
        )
        render_info_panel(
            console,
            "执行状态",
            f"⚠️ 执行被阻断：{execution_plan.block_reason or '原因未知'}",
            style="yellow",
        )
    else:
        render_info_panel(console, "执行状态", "⚠️ 当前信号未触发下单。", style="yellow")


def _render_instrument_block(
    index: int,
    engine: TradingEngine,
    item: Dict[str, Any],
    account_snapshot: Optional[Dict[str, float]],
    perf_stats: Optional[Dict[str, Any]],
    daily_stats: Optional[Dict[str, Any]],
    notifier: Optional[Notifier],
    notify_level: str,
    positions_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[int, str]:
    temp_console = Console(record=True)
    process_instrument(
        engine,
        temp_console,
        item,
        account_snapshot=account_snapshot,
        perf_stats=perf_stats,
        daily_stats=daily_stats,
        notifier=notifier,
        notify_level=notify_level,
        positions_map=positions_map,
    )
    text = temp_console.export_text(styles=True)
    return index, text


def format_protection_value(target: ProtectionTarget) -> str:
    mode = target.mode or "-"
    trigger_type = target.trigger_type or "last"
    order_type = target.order_type or "market"
    if target.trigger_ratio:
        pct = target.trigger_ratio * 100
        return f"{pct:.1f}% ({mode}, {trigger_type}, {order_type})"
    if target.trigger_px:
        return f"{target.trigger_px:.6f} ({mode}, {trigger_type}, {order_type})"
    return f"- ({mode})"


def display_signal(signal: TradeSignal, console: Console) -> None:
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_row("操作", signal.action.value.upper())
    table.add_row("置信度", f"{signal.confidence:.2f}")
    table.add_row("数量", f"{signal.size}")
    protection = signal.protection
    if protection and protection.take_profit:
        table.add_row(
            "止盈",
            format_protection_value(protection.take_profit),
        )
    if protection and protection.stop_loss:
        table.add_row(
            "止损",
            format_protection_value(protection.stop_loss),
        )
    render_info_panel(console, "策略信号", table, style="bold yellow")


def display_execution_plan(plan: ExecutionPlan, console: Console) -> None:
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_row("模式", plan.order_type.upper())
    table.add_row("数量", f"{plan.size:.6f}")
    table.add_row("交易模式", plan.td_mode or "-")
    table.add_row("持仓方向", plan.pos_side or "-")
    table.add_row("预计滑点", f"{plan.est_slippage:.2%}")
    if plan.price:
        table.add_row("目标价格", f"{plan.price:.6f}")
    status = "阻断" if plan.blocked else "可执行"
    if plan.block_reason:
        status = f"{status} - {plan.block_reason}"
    table.add_row("状态", status)
    if plan.notes:
        table.add_row("提示", " / ".join(plan.notes))
    if plan.protection:
        if plan.protection.take_profit:
            table.add_row(
                "止盈",
                format_protection_value(plan.protection.take_profit),
            )
        if plan.protection.stop_loss:
            table.add_row(
                "止损",
                format_protection_value(plan.protection.stop_loss),
            )
    render_info_panel(console, "执行计划", table, style="bold cyan")


def display_execution_feedback(report: ExecutionReport, console: Console) -> None:
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    title = "执行成功" if report.success else "执行失败"
    table.add_row("状态", title)
    table.add_row("单据类型", report.plan.order_type.upper())
    if report.code:
        table.add_row("错误码", str(report.code))
    if report.error:
        table.add_row("信息", report.error)
    else:
        table.add_row("信息", "下单完成，等待成交回执。")
    render_info_panel(console, "执行反馈", table, style="bold red")


def display_signal_summary(
    inst_id: str, timeframe: str, signal: TradeSignal, console: Console
) -> None:
    action_key = signal.action.value.lower()
    emoji = ACTION_EMOJI.get(action_key, "ℹ️")
    size_text = f"{signal.size:.6f}"
    if signal.size <= 0:
        size_text = "0 (资金受限)"
    console.print(
        f"{emoji} {signal.action.value.upper()} @ {timeframe} size={size_text} conf={signal.confidence:.2f}"
    )


def display_balance(
    balance: Dict[str, List[Dict[str, str]]],
    console: Console,
    perf_stats: Optional[Dict[str, Any]] = None,
) -> None:
    data = balance.get("data", [])
    if not data:
        print_centered(console, "[yellow]账户余额信息为空[/yellow]")
        return
    entry = data[0]
    total_eq = float(entry.get("totalEq", 0) or 0)
    cash_avail = float(entry.get("cashBal", 0) or 0)
    details = entry.get("details", [])
    if details:
        try:
            cash_avail = sum(float(item.get("availBal", 0) or 0) for item in details)
        except Exception:
            cash_avail = float(entry.get("cashBal", 0) or 0)
    ratio = (cash_avail / total_eq) if total_eq else 0.0
    ratio_pct = f"{ratio * 100:.1f}%"
    render_section(
        console,
        f"账户总权益: {total_eq:.2f} USD",
        style="bold cyan",
    )
    print_centered(console, f"可用资金 {cash_avail:.2f} USD ({ratio_pct})")
    if not details:
        return
    table = Table(show_header=True, header_style="bold", box=box.SIMPLE)
    table.add_column("币种", justify="left")
    table.add_column("可用", justify="right")
    table.add_column("权益", justify="right")
    for item in details:
        ccy = item.get("ccy", "-")
        avail = item.get("availBal", "-")
        eq = item.get("eq", "-")
        table.add_row(str(ccy), str(avail), str(eq))
    print_centered(console, table)
    if perf_stats is not None:
        lookback = int(perf_stats.get("lookback_days", 0) or 0)
        sample_count = int(perf_stats.get("sample_count", 0) or 0)
        if sample_count > 0:
            stats_text = (
                f"📊 近{lookback}日 P/L {perf_stats.get('total_pnl', 0.0):+.2f} USDT | "
                f"胜率 {perf_stats.get('win_rate', 0.0) * 100:.0f}% "
                f"| 手续费 {perf_stats.get('fee_total', 0.0):+.2f} | 样本 {sample_count}"
            )
        else:
            stats_text = f"📊 近{lookback}日暂无成交数据"
        print_centered(console, stats_text)


def display_order_result(
    order_resp: Dict[str, Any], signal: TradeSignal, console: Console
) -> None:
    if order_resp.get("error"):
        _display_order_error(order_resp["error"], console)
        return
    data = order_resp.get("data") or []
    entry = data[0] if data else {}
    code = str(order_resp.get("code", ""))
    s_code = str(entry.get("sCode", ""))
    status_ok = code in ("0", "200") and s_code == "0"
    status = "成功" if status_ok else "失败"
    ts_text = entry.get("ts") or order_resp.get("outTime") or order_resp.get("inTime")
    ts_formatted = _format_timestamp(ts_text)
    if not status_ok:
        _display_order_error(
            {
                "code": code,
                "message": order_resp.get("msg"),
                "data": data,
            },
            console,
        )
        return
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_row("状态", status)
    table.add_row("订单ID", entry.get("ordId", "-"))
    if entry.get("clOrdId"):
        table.add_row("客户端ID", entry.get("clOrdId"))
    table.add_row("时间", ts_formatted)
    side = entry.get("side") or signal.action.value
    pos_side = entry.get("posSide")
    direction = side.upper()
    if pos_side:
        direction = f"{direction} ({pos_side})"
    table.add_row("方向", direction)
    size_txt = entry.get("sz") or entry.get("fillSz") or f"{signal.size:.6f}"
    table.add_row("数量", str(size_txt))
    table.add_row("策略置信度", f"{signal.confidence:.2f}")
    reason_summary = signal.reason.split("\n", 1)[0] if signal.reason else "-"
    if len(reason_summary) > 120:
        reason_summary = reason_summary[:117] + "..."
    table.add_row("信号摘要", reason_summary)
    avg_px = entry.get("avgPx") or entry.get("fillPx") or "-"
    table.add_row("均价", str(avg_px))
    fee = entry.get("fee") or entry.get("fillFee") or entry.get("execFee") or "-"
    table.add_row("手续费", str(fee))
    message = entry.get("sMsg") or order_resp.get("msg") or "-"
    table.add_row("信息", str(message))
    border_style = "green" if status_ok else "red"
    render_info_panel(console, "下单结果", table, style=border_style)


def _format_timestamp(ts: Any) -> str:
    if not ts:
        return "-"
    try:
        ts_int = int(ts)
        while ts_int > 1_000_000_000_000:
            ts_int //= 1000
        dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts)


def _display_order_error(error_info: Dict[str, Any], console: Console) -> None:
    code = str(error_info.get("code") or "")
    msg = error_info.get("message") or error_info.get("msg") or "未知错误"
    data = error_info.get("data") or []
    detail_code = ""
    detail_msg = ""
    if isinstance(data, list) and data:
        detail_code = str(data[0].get("sCode") or "")
        detail_msg = data[0].get("sMsg") or ""
    hint = ERROR_HINTS.get(detail_code or code, "请检查参数和资金设置后重试。")
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_row("状态", "下单失败")
    if code:
        table.add_row("错误码", code)
    if detail_code:
        table.add_row("子错误码", detail_code)
    table.add_row("信息", detail_msg or msg)
    table.add_row("建议", hint)
    render_info_panel(console, "下单错误", table, style="bold red")


def run_watchlist(
    engine: TradingEngine,
    console: Console,
    watchlist_manager: WatchlistManager,
    performance_tracker: PerformanceTracker,
    executor: ThreadPoolExecutor,
    market_stream: Optional[MarketDataStream] = None,
    notifier: Optional[Notifier] = None,
    notify_level: str = "critical",
    protection_monitor: Optional[ProtectionMonitor] = None,
) -> None:
    account_snapshot: Optional[Dict[str, float]] = None
    perf_stats: Optional[Dict[str, Any]] = None
    daily_stats: Optional[Dict[str, Any]] = None
    positions_map: Dict[str, List[Dict[str, Any]]] = {}
    try:
        balance = engine.okx.get_account_balance()
        perf_stats = performance_tracker.get_snapshot()
        daily_stats = performance_tracker.get_snapshot_for_days(1)
        display_balance(balance, console, perf_stats)
        account_snapshot = engine.build_account_snapshot(balance)
        if protection_monitor and hasattr(protection_monitor, "latest_positions"):
            positions_map = protection_monitor.latest_positions()
        else:
            try:
                positions_resp = engine.okx.get_positions(inst_type="SWAP")
                entries = positions_resp.get("data") or []
                for entry in entries:
                    inst = str(entry.get("instId") or "").upper()
                    if not inst:
                        continue
                    positions_map.setdefault(inst, []).append(entry)
            except Exception as exc:  # pragma: no cover
                logger.warning(f"查询持仓列表失败: {exc}")
    except Exception as exc:  # pragma: no cover
        print_centered(console, f"[red]查询余额失败: {exc}[/red]")
    refreshed = watchlist_manager.get_watchlist(account_snapshot)
    if not refreshed:
        print_centered(console, "[yellow]当前 watchlist 为空，跳过本轮。[/yellow]")
        return
    if market_stream:
        for entry in refreshed:
            higher = entry.get("higher_timeframes") or ()
            market_stream.ensure_subscriptions(
                entry["inst_id"],
                entry.get("timeframe", "5m"),
                higher,
            )
    futures = []
    results: List[Optional[str]] = [None] * len(refreshed)
    for idx, item in enumerate(refreshed):
        futures.append(
            executor.submit(
                _render_instrument_block,
                idx,
                engine,
                item,
                account_snapshot,
                perf_stats,
                daily_stats,
                notifier,
                notify_level,
                positions_map,
            )
        )
    for future in as_completed(futures):
        try:
            idx, text = future.result()
            results[idx] = text
        except Exception as exc:  # pragma: no cover
            logger.exception(f"处理合约失败: {exc}")
    for text in results:
        if text:
            console.print(Text.from_ansi(text), end="")
    if protection_monitor:
        protection_monitor.enforce()


def main() -> None:
    console = Console()
    executor: Optional[ThreadPoolExecutor] = None
    market_stream: Optional[MarketDataStream] = None
    notifier: Optional[Notifier] = None
    protection_monitor: Optional[ProtectionMonitor] = None
    try:
        settings = get_settings()
        startup_mode = getattr(settings.runtime, "startup_mode", "minimal").strip().lower()

        # 根据配置选择启动模式
        if startup_mode == "full":
            _confirm_launch(console)
        else:
            _minimal_launch(console)

        _configure_runtime(settings.runtime)
        worker_count = _estimate_worker_count(settings.runtime)
        batch_max, batch_wait = _derive_batch_config(worker_count)
        okx = OKXClient(settings)
        analyzer = MarketAnalyzer(settings)
        strategy = Strategy()
        try:
            market_stream = MarketDataStream()
        except Exception as exc:
            console.print(
                f"[yellow]WebSocket 行情流启动失败: {exc}，将回退 REST。[/yellow]"
            )
            market_stream = None
        notifier = build_notifier(
            settings.notification.enabled,
            settings.notification.telegram_bot_token,
            settings.notification.telegram_chat_id,
            settings.notification.telegram_api_url,
            settings.notification.cooldown_seconds,
        )
        notify_level = (settings.notification.level or "critical").strip().lower()
        engine = TradingEngine(
            okx, analyzer, strategy, settings, market_stream=market_stream
        )
        watchlist_manager = WatchlistManager(okx, settings)
        performance_tracker = PerformanceTracker(okx)
        executor = ThreadPoolExecutor(max_workers=worker_count)
        thresholds = ProtectionThresholds(
            take_profit_pct=getattr(settings.strategy, "default_take_profit_pct", 0.0)
            or 0.0,
            stop_loss_pct=getattr(settings.strategy, "default_stop_loss_pct", 0.0)
            or 0.0,
        )
        protection_monitor = ProtectionMonitor(
            okx_client=okx,
            thresholds=thresholds,
            default_td_mode=settings.account.okx_td_mode or "cross",
            interval_seconds=getattr(
                settings.runtime, "protection_monitor_interval_seconds", 30.0
            )
            or 30.0,
        )
        protection_monitor.start()

        run_watchlist(
            engine,
            console,
            watchlist_manager,
            performance_tracker,
            executor,
            market_stream=market_stream,
            notifier=notifier,
            notify_level=notify_level,
            protection_monitor=protection_monitor,
        )
        schedule.every(RUN_INTERVAL_MINUTES).minutes.do(
            run_watchlist,
            engine=engine,
            console=console,
            watchlist_manager=watchlist_manager,
            performance_tracker=performance_tracker,
            executor=executor,
            market_stream=market_stream,
            notifier=notifier,
            notify_level=notify_level,
            protection_monitor=protection_monitor,
        )

        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("收到退出信号，停止运行。")
    finally:
        if executor:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass
        if market_stream:
            market_stream.close()
        if protection_monitor:
            protection_monitor.stop()
        notifier = None


if __name__ == "__main__":
    main()
