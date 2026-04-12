"""新闻/舆情情报模块测试。"""

from __future__ import annotations

from types import SimpleNamespace

from core.analysis.intel import NewsIntelCollector, _detect_event_tags, _score_text


def test_score_text_positive_and_negative() -> None:
    pos, tags_pos = _score_text("Bitcoin rally and approval with strong inflow")
    neg, tags_neg = _score_text("Exchange hack and security breach cause liquidation")
    assert pos > 0
    assert neg < 0
    assert tags_pos == []
    assert "hack" in tags_neg or "security breach" in tags_neg


def test_detect_event_tags_returns_weights() -> None:
    tags = _detect_event_tags("SEC investigation after exchange hack while CPI rises before FOMC.")
    assert tags["regulation"] > 0
    assert tags["security"] > 0
    assert tags["macro"] > 0


def test_news_intel_collector_collect(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="k",
        news_timeout_seconds=3.0,
        news_limit=5,
        news_window_hours=24,
        sentiment_enabled=True,
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "status": "ok",
                "articles": [
                    {
                        "title": "Bitcoin rally after ETF inflow",
                        "description": "Strong adoption narrative",
                        "source": {"name": "demo"},
                        "publishedAt": "2026-01-01T00:00:00Z",
                        "url": "https://x/a",
                    },
                    {
                        "title": "Bitcoin rally after ETF inflow",  # duplicate title
                        "description": "dup",
                        "source": {"name": "demo"},
                        "publishedAt": "2026-01-01T00:01:00Z",
                        "url": "https://x/b",
                    },
                    {
                        "title": "Bitcoin security breach sparks fear",
                        "description": "possible bitcoin hack event",
                        "source": {"name": "demo2"},
                        "publishedAt": "2026-01-01T00:02:00Z",
                        "url": "https://x/c",
                    },
                ],
            }

    def _fake_get(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("core.analysis.intel.requests.get", _fake_get)
    snapshot = collector.collect("BTC-USDT-SWAP")

    assert snapshot is not None
    assert snapshot.inst_id == "BTC-USDT-SWAP"
    assert snapshot.provider == "newsapi"
    assert len(snapshot.headlines) == 2  # dedup by title+source+window
    assert -1.0 <= snapshot.sentiment_score <= 1.0
    assert snapshot.event_risk_score > 0
    assert "security" in snapshot.event_tags
    assert isinstance(snapshot.summary, str)


def test_news_intel_collector_source_filter_and_window_dedupe(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="k",
        news_timeout_seconds=3.0,
        news_limit=10,
        news_window_hours=24,
        sentiment_enabled=True,
        news_source_whitelist="trusted",
        news_source_blacklist="spam",
        news_dedupe_window_minutes=60,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "status": "ok",
                "articles": [
                    {
                        "title": "BTC reacts to regulation update",
                        "description": "Policy headline",
                        "source": {"name": "trusted"},
                        "publishedAt": "2026-01-01T00:00:00Z",
                        "url": "https://x/a",
                    },
                    {
                        "title": "BTC reacts to regulation update",
                        "description": "duplicate in same window",
                        "source": {"name": "trusted"},
                        "publishedAt": "2026-01-01T00:30:00Z",
                        "url": "https://x/b",
                    },
                    {
                        "title": "BTC reacts to regulation update",
                        "description": "same source but outside dedupe window",
                        "source": {"name": "trusted"},
                        "publishedAt": "2026-01-01T02:30:00Z",
                        "url": "https://x/c",
                    },
                    {
                        "title": "BTC reacts to regulation update",
                        "description": "not in whitelist",
                        "source": {"name": "other"},
                        "publishedAt": "2026-01-01T00:10:00Z",
                        "url": "https://x/d",
                    },
                    {
                        "title": "Macro risk is rising",
                        "description": "blacklist source",
                        "source": {"name": "spam"},
                        "publishedAt": "2026-01-01T00:11:00Z",
                        "url": "https://x/e",
                    },
                ],
            }

    monkeypatch.setattr("core.analysis.intel.requests.get", lambda *args, **kwargs: _Resp())
    snapshot = collector.collect("BTC-USDT-SWAP")

    assert snapshot is not None
    assert len(snapshot.headlines) == 2
    assert all(item.source == "trusted" for item in snapshot.headlines)


def test_news_intel_collector_resolve_query_prefers_override_and_symbol_map() -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="k",
        news_timeout_seconds=3.0,
        news_limit=5,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases='{"JELLYJELLY":["JellyJelly","JELLYJELLY token"],"OL":["Orange Labs"]}',
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    assert collector.resolve_query("JELLYJELLY-USDT-SWAP") == 'JellyJelly OR "JELLYJELLY token"'
    assert collector.resolve_query("2Z-USDT-SWAP") == '"2Z" AND (crypto OR token OR coin OR blockchain)'
    assert collector.resolve_query(
        "OL-USDT-SWAP",
        symbol_aliases=("OL Network", "OL token"),
    ) == '"OL Network" OR "OL token"'
    assert collector.resolve_query(
        "BTC-USDT-SWAP",
        query_override='"Bitcoin" AND ETF',
    ) == '"Bitcoin" AND ETF'


def test_news_intel_collector_aggregate_multiple_providers(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_providers="coingecko,newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="news-k",
        news_timeout_seconds=3.0,
        news_limit=10,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases="",
        news_coin_ids='{"BTC":"bitcoin"}',
        coingecko_api_base="https://example.com/api/v3",
        coingecko_api_key="cg-k",
        coingecko_news_language="en",
        coingecko_news_type="news",
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    monkeypatch.setattr(
        collector,
        "_fetch_newsapi",
        lambda query: [
            {
                "title": "Bitcoin rally after ETF inflow",
                "description": "Adoption rises",
                "source": {"name": "wire"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "url": "https://n/1",
                "_provider": "newsapi",
            },
            {
                "title": "Macro risk drives volatility",
                "description": "FOMC and CPI drive caution",
                "source": {"name": "macro"},
                "publishedAt": "2026-01-01T00:10:00Z",
                "url": "https://n/2",
                "_provider": "newsapi",
            },
        ],
    )
    monkeypatch.setattr(
        collector,
        "_fetch_coingecko_news_by_coin_id",
        lambda coin_id: [
            {
                "title": "Bitcoin rally after ETF inflow",
                "description": "duplicate across providers",
                "source": {"name": "wire"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "url": "https://cg/1",
                "_provider": "coingecko",
            },
            {
                "title": "Bitcoin exchange hack sparks fear",
                "description": "possible bitcoin exploit",
                "source": {"name": "alert"},
                "publishedAt": "2026-01-01T00:20:00Z",
                "url": "https://cg/2",
                "_provider": "coingecko",
            },
        ],
    )

    snapshot = collector.collect("BTC-USDT-SWAP")

    assert snapshot is not None
    assert snapshot.provider == "coingecko+newsapi"
    assert snapshot.providers == ["coingecko", "newsapi"]
    assert snapshot.coverage_count == 2
    assert len(snapshot.headlines) == 2
    assert {item.provider for item in snapshot.headlines} == {"newsapi", "coingecko"}
    assert "security" in snapshot.event_tags
    assert snapshot.provider_counts == {"coingecko": 1, "newsapi": 1}


def test_news_intel_collector_resolve_coin_id_prefers_override_and_map() -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_providers="coingecko,newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="news-k",
        news_timeout_seconds=3.0,
        news_limit=5,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases='{"JELLYJELLY":["JellyJelly"]}',
        news_coin_ids='{"JELLYJELLY":"jelly-my-jelly"}',
        coingecko_api_base="https://example.com/api/v3",
        coingecko_api_key="cg-k",
        coingecko_news_language="en",
        coingecko_news_type="news",
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    assert collector.resolve_coin_id("JELLYJELLY-USDT-SWAP") == "jelly-my-jelly"
    assert collector.resolve_coin_id("BTC-USDT-SWAP") == "bitcoin"
    assert collector.resolve_coin_id(
        "OL-USDT-SWAP",
        coin_id_override="open-loot",
    ) == "open-loot"


def test_coingecko_generic_feed_is_filtered_by_alias_relevance(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_providers="coingecko",
        news_api_base="https://example.com/v2/everything",
        news_api_key="news-k",
        news_timeout_seconds=3.0,
        news_limit=10,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases="",
        news_coin_ids='{"JELLYJELLY":"jelly-my-jelly"}',
        coingecko_api_base="https://example.com/api/v3",
        coingecko_api_key="cg-k",
        coingecko_news_language="en",
        coingecko_news_type="news",
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    monkeypatch.setattr(
        collector,
        "_fetch_coingecko_news_by_coin_id",
        lambda coin_id: [
            {
                "title": "Japan brings crypto into regulated finance sector",
                "description": "generic market headline",
                "source": {"name": "cg"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "url": "https://cg/1",
                "_provider": "coingecko",
            },
            {
                "title": "Jelly-My-Jelly expands ecosystem",
                "description": "project-specific mention",
                "source": {"name": "cg"},
                "publishedAt": "2026-01-01T00:01:00Z",
                "url": "https://cg/2",
                "_provider": "coingecko",
            },
        ],
    )

    snapshot = collector.collect(
        "JELLYJELLY-USDT-SWAP",
        coin_id_override="jelly-my-jelly",
        symbol_aliases=("Jelly-My-Jelly", "JellyJelly"),
    )

    assert snapshot is not None
    assert len(snapshot.headlines) == 1
    assert snapshot.headlines[0].title == "Jelly-My-Jelly expands ecosystem"


def test_newsapi_articles_are_filtered_by_alias_relevance(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_providers="newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="news-k",
        news_timeout_seconds=3.0,
        news_limit=10,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases="",
        news_coin_ids="",
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    monkeypatch.setattr(
        collector,
        "_fetch_newsapi",
        lambda query: [
            {
                "title": "Open Loot expands creator ecosystem",
                "description": "Open Loot partnership attracts new studios",
                "source": {"name": "wire"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "url": "https://n/1",
                "_provider": "newsapi",
            },
            {
                "title": "Open market activity remains weak",
                "description": "Loot boxes in gaming remain controversial",
                "source": {"name": "wire"},
                "publishedAt": "2026-01-01T00:05:00Z",
                "url": "https://n/2",
                "_provider": "newsapi",
            },
        ],
    )

    snapshot = collector.collect(
        "OL-USDT-SWAP",
        symbol_aliases=("Open Loot", "OpenLoot"),
    )

    assert snapshot is not None
    assert len(snapshot.headlines) == 1
    assert snapshot.headlines[0].title == "Open Loot expands creator ecosystem"


def test_headline_exposes_relevance_score_and_matched_aliases(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_providers="newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="news-k",
        news_timeout_seconds=3.0,
        news_limit=10,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases="",
        news_coin_ids="",
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    monkeypatch.setattr(
        collector,
        "_fetch_newsapi",
        lambda query: [
            {
                "title": "Bitcoin rally after ETF inflow",
                "description": "Bitcoin adoption rises again",
                "source": {"name": "wire"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "url": "https://n/1",
                "_provider": "newsapi",
            }
        ],
    )

    snapshot = collector.collect(
        "BTC-USDT-SWAP",
        symbol_aliases=("Bitcoin", "BTC"),
    )

    assert snapshot is not None
    assert snapshot.analysis_version == "v2"
    assert snapshot.headlines[0].relevance_score > 0.5
    assert "Bitcoin" in snapshot.headlines[0].matched_aliases
    assert snapshot.avg_relevance_score > 0.0


def test_sentiment_is_weighted_by_relevance(monkeypatch) -> None:
    settings = SimpleNamespace(
        news_enabled=True,
        news_provider="newsapi",
        news_providers="newsapi",
        news_api_base="https://example.com/v2/everything",
        news_api_key="news-k",
        news_timeout_seconds=3.0,
        news_limit=10,
        news_window_hours=24,
        sentiment_enabled=True,
        news_symbol_aliases="",
        news_coin_ids="",
        news_source_whitelist="",
        news_source_blacklist="",
        news_dedupe_window_minutes=120,
        event_tag_enabled=True,
    )
    collector = NewsIntelCollector(settings)

    monkeypatch.setattr(
        collector,
        "_fetch_newsapi",
        lambda query: [
            {
                "title": "Bitcoin rally after ETF inflow",
                "description": "Bitcoin approval drives adoption and breakout",
                "source": {"name": "wire"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "url": "https://n/1",
                "_provider": "newsapi",
            },
            {
                "title": "Crypto market faces hack concerns",
                "description": "A generic security breach headline mentions BTC once in passing",
                "source": {"name": "wire2"},
                "publishedAt": "2026-01-01T00:10:00Z",
                "url": "https://n/2",
                "_provider": "newsapi",
            },
        ],
    )

    snapshot = collector.collect(
        "BTC-USDT-SWAP",
        symbol_aliases=("Bitcoin", "BTC"),
    )

    assert snapshot is not None
    assert snapshot.sentiment_score > 0.2
