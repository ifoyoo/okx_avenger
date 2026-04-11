"""PerformanceTracker 统计测试。"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from core.data.performance import PerformanceTracker


def test_compute_stats_includes_consecutive_losses(tmp_path, monkeypatch) -> None:
    tracker = PerformanceTracker(
        okx_client=SimpleNamespace(),
        cache_path=Path(tmp_path) / "perf_cache.json",
        lookback_days=7,
        refresh_minutes=15,
    )

    now_ms = int(time.time() * 1000)
    fills = [
        {"ts": str(now_ms), "fillPnl": "-12.0", "fee": "-0.2", "tradeId": "t3"},
        {"ts": str(now_ms - 1_000), "fillPnl": "-5.0", "fee": "-0.1", "tradeId": "t2"},
        {"ts": str(now_ms - 2_000), "fillPnl": "8.0", "fee": "-0.1", "tradeId": "t1"},
    ]
    monkeypatch.setattr(tracker, "_fetch_recent_fills", lambda since_ms, lookback_days: fills)

    stats, _trade_id = tracker._compute_stats_for_days(1)

    assert stats is not None
    assert stats["sample_count"] == 3
    assert stats["wins"] == 1
    assert stats["losses"] == 2
    assert stats["consecutive_losses"] == 2
