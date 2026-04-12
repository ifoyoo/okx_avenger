"""新闻/舆情情报采集与确定性预处理。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import requests
from loguru import logger


POSITIVE_TERMS = (
    "surge",
    "rally",
    "approval",
    "approved",
    "inflow",
    "breakout",
    "bull",
    "adoption",
    "record high",
    "partnership",
    "upgrade",
)
NEGATIVE_TERMS = (
    "hack",
    "exploit",
    "lawsuit",
    "ban",
    "crackdown",
    "liquidation",
    "outflow",
    "investigation",
    "fraud",
    "bear",
    "security breach",
    "depeg",
)
EVENT_TAG_TERMS: Dict[str, Dict[str, Any]] = {
    "regulation": {
        "keywords": (
            "sec",
            "regulator",
            "regulation",
            "regulatory",
            "lawsuit",
            "ban",
            "compliance",
            "investigation",
            "sanction",
            "policy",
            "etf rejection",
            "license revoked",
        ),
        "base_weight": 0.72,
    },
    "security": {
        "keywords": (
            "hack",
            "hacked",
            "exploit",
            "security breach",
            "vulnerability",
            "phishing",
            "private key leak",
            "wallet drained",
            "attack",
            "stolen",
            "drain",
            "ransomware",
        ),
        "base_weight": 0.78,
    },
    "macro": {
        "keywords": (
            "fed",
            "fomc",
            "interest rate",
            "rate hike",
            "rate cut",
            "cpi",
            "inflation",
            "recession",
            "gdp",
            "unemployment",
            "treasury yield",
            "dollar index",
            "liquidity",
        ),
        "base_weight": 0.58,
    },
}
SUPPORTED_NEWS_PROVIDERS = ("coingecko", "newsapi")
DEFAULT_COINGECKO_COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
}


def _symbol_aliases(symbol: str) -> List[str]:
    mapping = {
        "BTC": ["bitcoin", "btc"],
        "ETH": ["ethereum", "eth"],
        "SOL": ["solana", "sol"],
        "XRP": ["xrp", "ripple"],
        "DOGE": ["dogecoin", "doge"],
    }
    up = (symbol or "").upper()
    return mapping.get(up, [up.lower()])


def _coerce_aliases(raw: Any) -> List[str]:
    if raw in (None, "", ()):
        return []
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, Iterable):
        items = list(raw)
    else:
        items = [raw]
    aliases: List[str] = []
    seen: Set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        aliases.append(value)
    return aliases


def _parse_symbol_alias_map(raw: Any) -> Dict[str, List[str]]:
    if raw in (None, "", ()):
        return {}
    payload = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("NEWS_SYMBOL_ALIASES 不是合法 JSON，已忽略。")
            return {}
    if not isinstance(payload, dict):
        logger.warning("NEWS_SYMBOL_ALIASES 必须是 JSON object，已忽略。")
        return {}
    result: Dict[str, List[str]] = {}
    for key, value in payload.items():
        symbol = str(key or "").strip().upper()
        if not symbol:
            continue
        aliases = _coerce_aliases(value)
        if aliases:
            result[symbol] = aliases
    return result


def _parse_symbol_value_map(raw: Any) -> Dict[str, str]:
    if raw in (None, "", ()):
        return {}
    payload = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("NEWS_COIN_IDS 不是合法 JSON，已忽略。")
            return {}
    if not isinstance(payload, dict):
        logger.warning("NEWS_COIN_IDS 必须是 JSON object，已忽略。")
        return {}
    result: Dict[str, str] = {}
    for key, value in payload.items():
        symbol = str(key or "").strip().upper()
        mapped = str(value or "").strip()
        if symbol and mapped:
            result[symbol] = mapped
    return result


def _parse_provider_list(raw: Any, fallback: str) -> List[str]:
    items = _coerce_aliases(raw)
    if not items and fallback:
        items = [fallback]
    providers: List[str] = []
    seen: Set[str] = set()
    for item in items:
        provider = str(item or "").strip().lower()
        if not provider or provider in seen:
            continue
        seen.add(provider)
        providers.append(provider)
    return providers


def _format_query_term(term: str) -> str:
    value = str(term or "").strip()
    if not value:
        return ""
    needs_quotes = any(ch.isspace() for ch in value) or any(ch in value for ch in ('"', "(", ")", ":"))
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"' if needs_quotes else escaped


def _build_symbol_query(symbol: str, aliases: Sequence[str]) -> str:
    cleaned = [item for item in (_format_query_term(alias) for alias in aliases) if item]
    if cleaned:
        return " OR ".join(cleaned)
    token = str(symbol or "").strip().upper()
    if not token:
        return ""
    if len(token) <= 4:
        return f'"{token}" AND (crypto OR token OR coin OR blockchain)'
    return _format_query_term(token)


def _normalize_match_token(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _coerce_published_at_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e12:
            timestamp /= 1000.0
        try:
            parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return str(value)
        return parsed.isoformat()
    return str(value)


def _score_text(text: str) -> Tuple[float, List[str]]:
    lower = (text or "").lower()
    score = 0.0
    risk_tags: List[str] = []
    for item in POSITIVE_TERMS:
        if item in lower:
            score += 1.0
    for item in NEGATIVE_TERMS:
        if item in lower:
            score -= 1.0
            risk_tags.append(item)
    if score > 2:
        score = 2.0
    if score < -2:
        score = -2.0
    return score / 2.0, risk_tags


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_source(value: str) -> str:
    return _normalize_text(value)


def _parse_csv_set(raw: Any) -> Set[str]:
    if raw in (None, "", ()):
        return set()
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = str(raw).split(",")
    return {_normalize_source(item) for item in items if _normalize_source(str(item))}


def _parse_published_at(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe_key(title: str, source: str, published_at: str, window_minutes: int) -> str:
    title_key = _normalize_text(title)
    source_key = _normalize_source(source)
    published = _parse_published_at(published_at)
    if published is None:
        bucket = "na"
    else:
        window_seconds = max(60, int(window_minutes) * 60)
        bucket = str(int(published.timestamp() // window_seconds))
    return f"{title_key}|{source_key}|{bucket}"


def _detect_event_tags(text: str) -> Dict[str, float]:
    lower = (text or "").lower()
    tags: Dict[str, float] = {}
    for tag, config in EVENT_TAG_TERMS.items():
        keywords = tuple(config.get("keywords") or ())
        base_weight = float(config.get("base_weight") or 0.5)
        matched = sum(1 for keyword in keywords if keyword in lower)
        if matched <= 0:
            continue
        weight = min(1.0, base_weight + 0.08 * (matched - 1))
        tags[tag] = round(weight, 3)
    return tags


@dataclass
class NewsHeadline:
    title: str
    provider: str = ""
    source: str = ""
    published_at: str = ""
    url: str = ""
    sentiment: float = 0.0
    event_tags: List[str] = field(default_factory=list)
    risk_weight: float = 0.0
    relevance_score: float = 0.0
    matched_aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MarketIntelSnapshot:
    inst_id: str
    provider: str
    query: str
    sentiment_score: float
    risk_tags: List[str]
    event_tags: Dict[str, float]
    event_risk_score: float
    summary: str
    headlines: List[NewsHeadline]
    providers: List[str] = field(default_factory=list)
    coverage_count: int = 0
    analysis_version: str = "v2"
    matched_aliases: List[str] = field(default_factory=list)
    avg_relevance_score: float = 0.0
    provider_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inst_id": self.inst_id,
            "provider": self.provider,
            "query": self.query,
            "sentiment_score": self.sentiment_score,
            "risk_tags": list(self.risk_tags),
            "event_tags": dict(self.event_tags),
            "event_risk_score": self.event_risk_score,
            "summary": self.summary,
            "headlines": [item.to_dict() for item in self.headlines],
            "providers": list(self.providers),
            "coverage_count": self.coverage_count,
            "analysis_version": self.analysis_version,
            "matched_aliases": list(self.matched_aliases),
            "avg_relevance_score": self.avg_relevance_score,
            "provider_counts": dict(self.provider_counts),
        }


class NewsIntelCollector:
    """新闻 API 拉取 + 去重 + 情绪评分。"""

    def __init__(self, settings: Any) -> None:
        self.enabled = bool(getattr(settings, "news_enabled", False))
        self.provider = str(getattr(settings, "news_provider", "newsapi") or "newsapi")
        self.providers = _parse_provider_list(getattr(settings, "news_providers", ""), self.provider)
        self.api_base = str(getattr(settings, "news_api_base", "https://newsapi.org/v2/everything") or "").strip()
        self.api_key = str(getattr(settings, "news_api_key", "") or "")
        self.timeout_seconds = float(getattr(settings, "news_timeout_seconds", 6.0) or 6.0)
        self.limit = max(1, int(getattr(settings, "news_limit", 10) or 10))
        self.window_hours = max(1, int(getattr(settings, "news_window_hours", 24) or 24))
        self.sentiment_enabled = bool(getattr(settings, "sentiment_enabled", True))
        self.symbol_aliases = _parse_symbol_alias_map(getattr(settings, "news_symbol_aliases", ""))
        self.coin_ids = _parse_symbol_value_map(getattr(settings, "news_coin_ids", ""))
        self.source_whitelist = _parse_csv_set(getattr(settings, "news_source_whitelist", ""))
        self.source_blacklist = _parse_csv_set(getattr(settings, "news_source_blacklist", ""))
        self.dedupe_window_minutes = max(1, int(getattr(settings, "news_dedupe_window_minutes", 120) or 120))
        self.coingecko_api_base = str(
            getattr(settings, "coingecko_api_base", "https://pro-api.coingecko.com/api/v3") or ""
        ).strip()
        self.coingecko_api_key = str(getattr(settings, "coingecko_api_key", "") or "")
        self.coingecko_news_language = str(getattr(settings, "coingecko_news_language", "en") or "en").strip().lower()
        self.coingecko_news_type = str(getattr(settings, "coingecko_news_type", "news") or "news").strip().lower()
        self.event_tag_enabled = bool(getattr(settings, "event_tag_enabled", True))
        self._coin_id_cache: Dict[str, Optional[str]] = {}

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self._available_providers())

    def _available_providers(self) -> List[str]:
        available: List[str] = []
        for provider in self.providers:
            if provider == "newsapi":
                if self.api_base and self.api_key:
                    available.append(provider)
                continue
            if provider == "coingecko":
                if self.coingecko_api_base and self.coingecko_api_key:
                    available.append(provider)
                continue
        return available

    @staticmethod
    def _symbol_from_inst_id(inst_id: str) -> str:
        return str(inst_id or "").split("-")[0].upper()

    def resolve_alias_terms(
        self,
        inst_id: str,
        *,
        symbol_aliases: Optional[Sequence[str]] = None,
    ) -> List[str]:
        symbol = self._symbol_from_inst_id(inst_id)
        aliases = _coerce_aliases(symbol_aliases)
        if aliases:
            return aliases
        if symbol in self.symbol_aliases:
            return list(self.symbol_aliases[symbol])
        aliases = _symbol_aliases(symbol)
        if len(aliases) == 1 and str(aliases[0]).strip().lower() == symbol.lower():
            return [symbol]
        return aliases

    def resolve_query(
        self,
        inst_id: str,
        *,
        query_override: Optional[str] = None,
        symbol_aliases: Optional[Sequence[str]] = None,
    ) -> str:
        symbol = self._symbol_from_inst_id(inst_id)
        explicit = str(query_override or "").strip()
        if explicit:
            return explicit
        aliases = self.resolve_alias_terms(inst_id, symbol_aliases=symbol_aliases)
        if len(aliases) == 1 and str(aliases[0]).strip().upper() == symbol:
            return _build_symbol_query(symbol, [])
        return _build_symbol_query(symbol, aliases)

    def resolve_coin_id(
        self,
        inst_id: str,
        *,
        coin_id_override: Optional[str] = None,
        symbol_aliases: Optional[Sequence[str]] = None,
    ) -> Optional[str]:
        explicit = str(coin_id_override or "").strip()
        if explicit:
            return explicit
        symbol = self._symbol_from_inst_id(inst_id)
        if symbol in self.coin_ids:
            return self.coin_ids[symbol]
        if symbol in DEFAULT_COINGECKO_COIN_IDS:
            return DEFAULT_COINGECKO_COIN_IDS[symbol]
        cache_key = f"{symbol}|{'|'.join(self.resolve_alias_terms(inst_id, symbol_aliases=symbol_aliases))}"
        if cache_key in self._coin_id_cache:
            return self._coin_id_cache[cache_key]
        aliases = self.resolve_alias_terms(inst_id, symbol_aliases=symbol_aliases)
        if len(symbol) <= 4 and not any(len(str(item or "").strip()) > 4 for item in aliases):
            self._coin_id_cache[cache_key] = None
            return None
        resolved = self._search_coingecko_coin_id(symbol, aliases)
        self._coin_id_cache[cache_key] = resolved
        return resolved

    def collect(
        self,
        inst_id: str,
        *,
        query_override: Optional[str] = None,
        coin_id_override: Optional[str] = None,
        symbol_aliases: Optional[Sequence[str]] = None,
    ) -> Optional[MarketIntelSnapshot]:
        if not self.ready:
            return None
        query = self.resolve_query(inst_id, query_override=query_override, symbol_aliases=symbol_aliases)
        if not query:
            return None
        aliases = self.resolve_alias_terms(inst_id, symbol_aliases=symbol_aliases)
        articles, active_providers = self._fetch_articles(
            inst_id=inst_id,
            query=query,
            coin_id_override=coin_id_override,
            symbol_aliases=symbol_aliases,
        )
        articles = self._filter_and_score_articles(articles, aliases)
        articles = sorted(articles, key=self._article_rank_key, reverse=True)
        if not articles:
            return None
        headlines: List[NewsHeadline] = []
        weighted_sentiment_total = 0.0
        sentiment_weight_total = 0.0
        risk_tags: List[str] = []
        event_weights: Dict[str, float] = {}
        matched_aliases: Set[str] = set()
        seen = set()
        for item in articles:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            provider = str(item.get("_provider") or "")
            source = ""
            source_raw = item.get("source")
            if isinstance(source_raw, dict):
                source = str(source_raw.get("name") or "")
            elif source_raw:
                source = str(source_raw)
            if not self._allow_source(source):
                continue
            published = str(item.get("publishedAt") or item.get("published_at") or "")
            dedupe_key = _dedupe_key(
                title=title,
                source=source,
                published_at=published,
                window_minutes=self.dedupe_window_minutes,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            url = str(item.get("url") or "")
            relevance_score = max(0.0, min(1.0, float(item.get("_relevance_score") or 0.0)))
            headline_aliases = list(item.get("_matched_aliases") or [])
            matched_aliases.update(headline_aliases)
            sentiment = 0.0
            local_tags: List[str] = []
            local_events: Dict[str, float] = {}
            body = f"{title}\n{item.get('description') or ''}\n{item.get('content') or ''}"
            if self.sentiment_enabled:
                sentiment, local_tags = _score_text(body)
                weight = max(0.2, relevance_score)
                weighted_sentiment_total += sentiment * weight
                sentiment_weight_total += weight
                risk_tags.extend(local_tags)
            if self.event_tag_enabled:
                local_events = _detect_event_tags(body)
                for tag, weight in local_events.items():
                    prev = event_weights.get(tag, 0.0)
                    weighted = min(1.0, weight * (0.5 + 0.5 * relevance_score))
                    if weighted > prev:
                        event_weights[tag] = round(weighted, 3)
            headlines.append(
                NewsHeadline(
                    title=title,
                    provider=provider,
                    source=source,
                    published_at=published,
                    url=url,
                    sentiment=sentiment,
                    event_tags=sorted(local_events.keys()),
                    risk_weight=max(local_events.values()) if local_events else 0.0,
                    relevance_score=relevance_score,
                    matched_aliases=headline_aliases,
                )
            )
            if len(headlines) >= self.limit:
                break
        if not headlines:
            return None
        score = weighted_sentiment_total / sentiment_weight_total if sentiment_weight_total > 0 else 0.0
        score = max(-1.0, min(1.0, score))
        event_tags = dict(sorted(event_weights.items(), key=lambda item: item[0]))
        event_risk_score = max(event_tags.values()) if event_tags else 0.0
        avg_relevance_score = (
            sum(item.relevance_score for item in headlines) / len(headlines)
            if headlines else 0.0
        )
        provider_counts = self._collect_provider_counts(headlines)
        summary = self._build_summary(
            headlines=headlines,
            score=score,
            event_tags=event_tags,
            event_risk_score=event_risk_score,
            avg_relevance_score=avg_relevance_score,
            provider_counts=provider_counts,
        )
        unique_risks = sorted(set(risk_tags))
        return MarketIntelSnapshot(
            inst_id=inst_id,
            provider="+".join(self._available_providers()),
            query=query,
            sentiment_score=score,
            risk_tags=unique_risks,
            event_tags=event_tags,
            event_risk_score=event_risk_score,
            summary=summary,
            headlines=headlines[: self.limit],
            providers=active_providers,
            coverage_count=len(headlines),
            matched_aliases=sorted(matched_aliases),
            avg_relevance_score=round(avg_relevance_score, 3),
            provider_counts=provider_counts,
        )

    def _fetch_articles(
        self,
        *,
        inst_id: str,
        query: str,
        coin_id_override: Optional[str],
        symbol_aliases: Optional[Sequence[str]],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        articles: List[Dict[str, Any]] = []
        active_providers: List[str] = []
        aliases = self.resolve_alias_terms(inst_id, symbol_aliases=symbol_aliases)
        for provider in self._available_providers():
            provider_articles: List[Dict[str, Any]] = []
            if provider == "newsapi":
                provider_articles = self._fetch_newsapi(query)
            elif provider == "coingecko":
                coin_id = self.resolve_coin_id(
                    inst_id,
                    coin_id_override=coin_id_override,
                    symbol_aliases=symbol_aliases,
                )
                if not coin_id:
                    logger.info("CoinGecko 情报跳过 inst={} reason=no_coin_id", inst_id)
                    continue
                provider_articles = self._fetch_coingecko_news_by_coin_id(coin_id)
                provider_articles = self._filter_relevant_articles(provider_articles, aliases)
            else:
                logger.warning("未支持的 NEWS_PROVIDER={}，已跳过情报抓取。", provider)
                continue
            if provider_articles:
                active_providers.append(provider)
                articles.extend(provider_articles)
        return articles, active_providers

    @staticmethod
    def _article_sort_key(item: Dict[str, Any]) -> float:
        published = _parse_published_at(
            item.get("publishedAt") or item.get("published_at") or item.get("created_at") or ""
        )
        if published is None:
            return 0.0
        return float(published.timestamp())

    @classmethod
    def _article_rank_key(cls, item: Dict[str, Any]) -> Tuple[float, float]:
        relevance = max(0.0, min(1.0, float(item.get("_relevance_score") or 0.0)))
        provider_priority = cls._provider_priority(str(item.get("_provider") or ""))
        return relevance, cls._article_sort_key(item), float(provider_priority)

    @staticmethod
    def _provider_priority(provider: str) -> int:
        normalized = str(provider or "").strip().lower()
        if normalized == "newsapi":
            return 2
        if normalized == "coingecko":
            return 1
        return 0

    def _filter_and_score_articles(
        self,
        articles: Sequence[Dict[str, Any]],
        aliases: Sequence[str],
    ) -> List[Dict[str, Any]]:
        if not articles:
            return []
        minimum = self._min_relevance_threshold(aliases)
        filtered: List[Dict[str, Any]] = []
        for item in articles:
            relevance_score, matched_aliases = self._score_article_relevance(item, aliases)
            if relevance_score + 1e-12 < minimum:
                continue
            article = dict(item)
            article["_relevance_score"] = round(relevance_score, 3)
            article["_matched_aliases"] = matched_aliases
            filtered.append(article)
        return filtered

    @staticmethod
    def _min_relevance_threshold(aliases: Sequence[str]) -> float:
        lengths = [len(_normalize_match_token(item)) for item in aliases if _normalize_match_token(item)]
        if not lengths:
            return 0.0
        if all(length <= 4 for length in lengths):
            return 0.55
        if any(length <= 4 for length in lengths):
            return 0.5
        return 0.35

    @classmethod
    def _score_article_relevance(
        cls,
        article: Dict[str, Any],
        aliases: Sequence[str],
    ) -> Tuple[float, List[str]]:
        title = str(article.get("title") or "")
        description = str(article.get("description") or "")
        content = str(article.get("content") or "")
        url = str(article.get("url") or "")

        matched_aliases: List[str] = []
        score = 0.0
        for alias in aliases:
            alias_text = str(alias or "").strip()
            if not alias_text:
                continue
            alias_len = len(_normalize_match_token(alias_text))
            title_hit = cls._alias_match_score(title, alias_text)
            description_hit = cls._alias_match_score(description, alias_text)
            content_hit = cls._alias_match_score(content, alias_text)
            url_hit = cls._alias_match_score(url, alias_text)
            alias_score = 0.0
            if title_hit:
                alias_score += 0.64 if alias_len <= 4 else 0.58
            if description_hit:
                alias_score += 0.18 if alias_len <= 4 else 0.24
            if content_hit:
                alias_score += 0.12 if alias_len <= 4 else 0.16
            if url_hit:
                alias_score += 0.1
            alias_score = min(1.0, alias_score)
            if alias_score <= 0:
                continue
            matched_aliases.append(alias_text)
            score = max(score, alias_score)
        unique_aliases = []
        seen: Set[str] = set()
        for alias in matched_aliases:
            if alias.lower() in seen:
                continue
            seen.add(alias.lower())
            unique_aliases.append(alias)
        return score, unique_aliases

    @staticmethod
    def _alias_match_score(value: str, alias: str) -> bool:
        haystack = str(value or "").strip()
        needle = str(alias or "").strip()
        if not haystack or not needle:
            return False
        haystack_lower = haystack.lower()
        needle_lower = needle.lower()
        normalized_alias = _normalize_text(needle_lower)
        alias_token = _normalize_match_token(needle_lower)
        haystack_token = _normalize_match_token(haystack_lower)
        token_len = len(alias_token)
        if not alias_token:
            return False
        if token_len <= 4:
            boundary_pattern = r"(?<![a-z0-9])" + re.escape(needle_lower) + r"(?![a-z0-9])"
            if re.search(boundary_pattern, haystack_lower):
                return True
            return alias_token in haystack_token and token_len > 2 and haystack_lower.startswith("http")
        if normalized_alias in _normalize_text(haystack_lower):
            return True
        return alias_token in haystack_token

    @staticmethod
    def _collect_provider_counts(headlines: Sequence[NewsHeadline]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in headlines:
            provider = str(item.provider or "").strip() or "unknown"
            counts[provider] = counts.get(provider, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: item[0]))

    def _fetch_newsapi(self, query: str) -> List[Dict[str, Any]]:
        from_time = datetime.now(timezone.utc) - timedelta(hours=self.window_hours)
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": str(self.limit),
            "from": from_time.isoformat(),
        }
        headers = {"X-Api-Key": self.api_key}
        try:
            resp = requests.get(
                self.api_base,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ok":
                logger.warning("NewsAPI 返回异常 status={} msg={}", data.get("status"), data.get("message"))
                return []
            articles = data.get("articles") or []
            if not isinstance(articles, list):
                return []
            return [self._normalize_article("newsapi", item) for item in articles if isinstance(item, dict)]
        except Exception as exc:  # pragma: no cover
            logger.warning("NewsAPI 请求失败 query={} err={}", query, exc)
            return []

    def _coingecko_headers(self) -> Dict[str, str]:
        if not self.coingecko_api_key:
            return {}
        base = self.coingecko_api_base.rstrip("/").lower()
        if "pro-api.coingecko.com" in base:
            return {"x-cg-pro-api-key": self.coingecko_api_key}
        return {"x-cg-demo-api-key": self.coingecko_api_key}

    def _search_coingecko_coin_id(self, symbol: str, aliases: Sequence[str]) -> Optional[str]:
        if not self.coingecko_api_base or not self.coingecko_api_key:
            return None
        candidates = [item for item in aliases if str(item or "").strip()]
        if not candidates:
            candidates = [symbol]
        headers = self._coingecko_headers()
        best_match: Tuple[int, Optional[str]] = (-1, None)
        for candidate in candidates:
            try:
                resp = requests.get(
                    f"{self.coingecko_api_base.rstrip('/')}/search",
                    params={"query": candidate},
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # pragma: no cover
                logger.warning("CoinGecko 搜索失败 query={} err={}", candidate, exc)
                continue
            coins = data.get("coins") or []
            if not isinstance(coins, list):
                continue
            for item in coins:
                if not isinstance(item, dict):
                    continue
                score = self._score_coingecko_coin(item, symbol, candidates)
                coin_id = str(item.get("id") or "").strip()
                if score > best_match[0] and coin_id:
                    best_match = (score, coin_id)
        return best_match[1]

    @staticmethod
    def _score_coingecko_coin(item: Dict[str, Any], symbol: str, candidates: Sequence[str]) -> int:
        symbol_key = _normalize_match_token(symbol)
        candidate_keys = {_normalize_match_token(symbol)}
        candidate_keys.update(_normalize_match_token(candidate) for candidate in candidates)
        candidate_keys.discard("")
        coin_id = _normalize_match_token(item.get("id"))
        coin_symbol = _normalize_match_token(item.get("symbol"))
        coin_name = _normalize_match_token(item.get("name"))
        score = 0
        if coin_symbol == symbol_key:
            score += 80
        if coin_id in candidate_keys:
            score += 70
        if coin_name in candidate_keys:
            score += 70
        if coin_symbol in candidate_keys:
            score += 40
        try:
            market_cap_rank = int(item.get("market_cap_rank") or 0)
        except (TypeError, ValueError):
            market_cap_rank = 0
        if market_cap_rank > 0:
            score += max(0, 20 - min(20, market_cap_rank // 50))
        return score

    def _fetch_coingecko_news_by_coin_id(self, coin_id: str) -> List[Dict[str, Any]]:
        params = {
            "coin_id": coin_id,
            "language": self.coingecko_news_language or "en",
            "per_page": str(self.limit),
            "page": "1",
            "type": self.coingecko_news_type or "news",
        }
        try:
            resp = requests.get(
                f"{self.coingecko_api_base.rstrip('/')}/news",
                params=params,
                headers=self._coingecko_headers(),
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                articles = data.get("data")
                if articles is None:
                    articles = data.get("items")
            else:
                articles = data
            if not isinstance(articles, list):
                return []
            return [
                self._normalize_article("coingecko", item, coin_id=coin_id)
                for item in articles
                if isinstance(item, dict)
            ]
        except Exception as exc:  # pragma: no cover
            logger.warning("CoinGecko News 请求失败 coin_id={} err={}", coin_id, exc)
            return []

    def _normalize_article(self, provider: str, item: Dict[str, Any], *, coin_id: Optional[str] = None) -> Dict[str, Any]:
        if provider == "coingecko":
            source_name = (
                item.get("source_name")
                or item.get("news_site")
                or item.get("source")
                or "CoinGecko"
            )
            title = item.get("title") or item.get("headline") or ""
            description = item.get("description") or item.get("text") or item.get("snippet") or ""
            content = item.get("content") or item.get("body") or ""
            published = (
                item.get("published_at")
                or item.get("created_at")
                or item.get("updated_at")
                or item.get("publishedAt")
                or ""
            )
            return {
                "title": title,
                "description": description,
                "content": content,
                "url": item.get("url") or item.get("news_url") or "",
                "publishedAt": _coerce_published_at_text(published),
                "source": {"name": str(source_name or "")},
                "_provider": provider,
                "_coin_id": coin_id or "",
            }
        article = dict(item)
        source = article.get("source")
        if not isinstance(source, dict):
            article["source"] = {"name": str(source or "")}
        article["_provider"] = provider
        return article

    @staticmethod
    def _filter_relevant_articles(articles: Sequence[Dict[str, Any]], aliases: Sequence[str]) -> List[Dict[str, Any]]:
        strong_terms = []
        for alias in aliases:
            value = str(alias or "").strip()
            if len(_normalize_match_token(value)) <= 2:
                continue
            strong_terms.append(value)
        if not strong_terms:
            return list(articles)
        matched: List[Dict[str, Any]] = []
        for item in articles:
            haystack = "\n".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("description") or ""),
                    str(item.get("content") or ""),
                    str(item.get("url") or ""),
                ]
            ).lower()
            if any(str(term).lower() in haystack for term in strong_terms):
                matched.append(dict(item))
        return matched

    def _allow_source(self, source: str) -> bool:
        normalized = _normalize_source(source)
        if normalized and normalized in self.source_blacklist:
            return False
        if self.source_whitelist and normalized not in self.source_whitelist:
            return False
        return True

    @staticmethod
    def _build_summary(
        headlines: List[NewsHeadline],
        score: float,
        event_tags: Dict[str, float],
        event_risk_score: float,
        avg_relevance_score: float,
        provider_counts: Dict[str, int],
    ) -> str:
        mood = "中性"
        if score >= 0.2:
            mood = "偏多"
        elif score <= -0.2:
            mood = "偏空"
        event_text = "事件标签: 无"
        if event_tags:
            parts = [f"{tag}:{weight:.2f}" for tag, weight in sorted(event_tags.items())]
            event_text = f"事件标签: {', '.join(parts)} (max={event_risk_score:.2f})"
        provider_text = "providers: 无"
        if provider_counts:
            provider_text = "providers: " + ", ".join(f"{name}={count}" for name, count in sorted(provider_counts.items()))
        top = [f"- {item.title}" for item in headlines[:3]]
        return (
            f"新闻情绪 {mood} (score={score:+.2f})\n"
            f"相关性均值 {avg_relevance_score:.2f}; {provider_text}\n"
            f"{event_text}\n"
            + "\n".join(top)
        )


def build_news_intel_collector(app_settings: Any) -> Optional[NewsIntelCollector]:
    intel_settings = getattr(app_settings, "intel", None)
    if intel_settings is None:
        return None
    collector = NewsIntelCollector(intel_settings)
    if not collector.enabled:
        return None
    if not collector.ready:
        logger.warning(
            "NEWS_ENABLED=true 但未配置可用的新闻源，已回退无情报模式。providers={}",
            ",".join(collector.providers),
        )
        return None
    return collector


__all__ = [
    "MarketIntelSnapshot",
    "NewsHeadline",
    "NewsIntelCollector",
    "build_news_intel_collector",
    "_detect_event_tags",
    "_score_text",
]
