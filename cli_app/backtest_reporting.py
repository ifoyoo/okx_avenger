from __future__ import annotations

from typing import Any, Dict, List, Tuple

from cli_app.backtest_helpers import _safe_float


def format_trade_lines(records: List[Dict[str, Any]], max_trades: int) -> List[str]:
    lines = ["", "=== Trades (latest first) ==="]
    for item in records:
        summary = item.get("summary") or {}
        trades = list(item.get("trades") or [])
        inst_id = str(summary.get("inst_id", "-"))
        timeframe = str(summary.get("timeframe", "-"))
        lines.append("")
        lines.append(f"[{inst_id} {timeframe}]")
        for trade in list(reversed(trades))[:max_trades]:
            side = str(trade.get("side", "-")).upper()
            qty = _safe_float(trade.get("qty"))
            entry = _safe_float(trade.get("entry_price"))
            exit_px = _safe_float(trade.get("exit_price"))
            net = _safe_float(trade.get("net_pnl"))
            held = int(_safe_float(trade.get("bars_held")))
            lines.append(
                f"- {side:<4} qty={qty:.6f} entry={entry:.6f} exit={exit_px:.6f} "
                f"net={net:+.4f} held={held}"
            )
    return lines


def format_tune_lines(
    *,
    lookback_bars: int,
    scanned_instruments: int,
    scores: Dict[str, float],
    weights: Dict[str, float],
    stats_rows: Dict[str, List[Tuple[int, float, float]]],
    regime_score_buckets: Dict[str, Dict[str, List[float]]],
) -> List[str]:
    lines = [
        "=== Backtest Tune ===",
        f"instruments={scanned_instruments} lookback_bars={lookback_bars}",
        f"{'plugin':<24} {'samples':<8} {'trades':<8} {'win_rate':<9} {'net_pnl':<12} {'score':<8} {'weight':<7}",
        "-" * 88,
    ]
    for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        weight = weights.get(name, 1.0)
        rows = stats_rows.get(name) or []
        samples = len(rows)
        avg_trades = sum(item[0] for item in rows) / samples if samples else 0.0
        avg_win_rate = sum(item[1] for item in rows) / samples if samples else 0.0
        avg_net = sum(item[2] for item in rows) / samples if samples else 0.0
        lines.append(
            f"{name:<24} {samples:<8d} {avg_trades:<8.1f} {avg_win_rate:>6.1f}%  {avg_net:>+10.2f}  {score:>+7.4f}  {weight:>5.2f}"
        )

    lines.append("")
    lines.append("=== Regime Buckets ===")
    for regime, per_plugin in sorted(regime_score_buckets.items(), key=lambda item: item[0]):
        lines.append(f"[{regime}]")
        regime_rows: List[Tuple[str, float]] = []
        for name, values in per_plugin.items():
            if values:
                regime_rows.append((name, sum(values) / len(values)))
        if not regime_rows:
            lines.append("- (no data)")
            continue
        for name, avg_score in sorted(regime_rows, key=lambda item: item[1], reverse=True):
            lines.append(f"- {name:<22} avg_score={avg_score:+.4f}")
    return lines
