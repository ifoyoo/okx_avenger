"""watchlist 解析测试。"""

from __future__ import annotations

from core.data.watchlist_loader import normalize_entry


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
