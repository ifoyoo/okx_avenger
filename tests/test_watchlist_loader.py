"""watchlist 解析测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.data.watchlist_loader import WatchlistManager, load_watchlist, normalize_entry


def test_normalize_entry_preserves_news_overrides() -> None:
    entry = normalize_entry(
        {
            "inst_id": "JELLYJELLY-USDT-SWAP",
            "timeframe": "5m",
            "higher_timeframes": ["1H"],
            "news_query": '"JellyJelly" AND (crypto OR token)',
            "news_coin_id": "jelly-my-jelly",
            "news_aliases": ["JellyJelly", "JELLYJELLY token"],
        }
    )

    assert entry["inst_id"] == "JELLYJELLY-USDT-SWAP"
    assert entry["news_query"] == '"JellyJelly" AND (crypto OR token)'
    assert entry["news_coin_id"] == "jelly-my-jelly"
    assert entry["news_aliases"] == ("JellyJelly", "JELLYJELLY token")


def test_normalize_entry_supports_string_shorthand_and_defaults() -> None:
    entry = normalize_entry("BTC-USDT-SWAP")

    assert entry["inst_id"] == "BTC-USDT-SWAP"
    assert entry["timeframe"] == "5m"
    assert entry["higher_timeframes"] == ("1H",)


def test_watchlist_manager_is_manual_only_and_does_not_require_mode_settings(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    watchlist_path.write_text('["BTC-USDT-SWAP"]', encoding="utf-8")

    manager = WatchlistManager(
        okx_client=object(),
        settings=SimpleNamespace(runtime=SimpleNamespace()),
    )
    manager._watchlist_path = watchlist_path

    assert manager.get_watchlist() == [
        {
            "inst_id": "BTC-USDT-SWAP",
            "timeframe": "5m",
            "higher_timeframes": ("1H",),
        }
    ]


def test_checked_in_watchlist_defaults_to_mixed_liquid_pool() -> None:
    entries = load_watchlist()

    assert [item["inst_id"] for item in entries] == [
        "BTC-USDT-SWAP",
        "ETH-USDT-SWAP",
        "SOL-USDT-SWAP",
        "XRP-USDT-SWAP",
        "DOGE-USDT-SWAP",
        "SUI-USDT-SWAP",
    ]
