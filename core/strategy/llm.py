"""LLM 分析封装."""

from __future__ import annotations

import atexit
import json
import queue
import time
from collections import OrderedDict, defaultdict, deque
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Deque, Dict, List, Optional, Tuple

import pandas as pd
from openai import OpenAI, AzureOpenAI
from loguru import logger

from config.settings import AppSettings

from .data_pipeline import build_market_summary, MarketSnapshot


@dataclass
class LLMAnalysis:
    text: str
    summary: str
    history_hint: str


@dataclass
class _LLMRequestPayload:
    request_id: str
    inst_id: str
    timeframe: str
    performance_hint: str
    snapshot_text: str
    summary_text: str
    account_context: str
    position_context: str
    pnl_context: str
    base_strategy_hint: str


_PERF_CACHE_MAXLEN = 64
_performance_cache_lock = Lock()
_performance_cache: Dict[Tuple[str, str], Deque[Dict]] = defaultdict(lambda: deque(maxlen=_PERF_CACHE_MAXLEN))
_performance_cache_loaded = False


class AIProvider(str, Enum):
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    MOONSHOT = "moonshot"
    QWEN = "qwen"
    GROK = "grok"


def _ensure_performance_cache_loaded() -> None:
    global _performance_cache_loaded
    if _performance_cache_loaded:
        return
    with _performance_cache_lock:
        if _performance_cache_loaded:
            return
        entries = _load_records()
        for rec in entries:
            inst = rec.get("inst_id")
            timeframe = rec.get("timeframe")
            if not inst or not timeframe:
                continue
            _performance_cache[(inst, timeframe)].append(rec)
        _performance_cache_loaded = True


def _register_performance_record(record: Dict[str, Any]) -> None:
    inst = record.get("inst_id")
    timeframe = record.get("timeframe")
    if not inst or not timeframe:
        return
    _ensure_performance_cache_loaded()
    with _performance_cache_lock:
        _performance_cache[(inst, timeframe)].append(record)


class LLMService:
    """为策略提供自然语言分析."""

    def __init__(
        self,
        settings: AppSettings,
        batch_max: Optional[int] = None,
        batch_wait: Optional[float] = None,
    ) -> None:
        self.settings = settings
        self.ai = settings.ai
        try:
            self.provider = AIProvider(str(self.ai.provider).strip().lower())
        except ValueError as exc:
            raise ValueError(f"Unsupported AI provider: {self.ai.provider}") from exc
        self._analysis_cache: OrderedDict[Tuple[str, str], Tuple[str, LLMAnalysis]] = OrderedDict()
        self._cache_limit = 64
        self._client, self._model = self._init_client()
        self._cache_path = Path("logs/llm-cache.json")
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_lock = Lock()
        self._load_cache_from_disk()
        self._cache_dirty = False
        self._last_cache_flush = 0.0
        self._cache_flush_interval = 15.0
        atexit.register(self._flush_cache_on_exit)
        self._analysis_guidance = (
            "策略守则：\n"
            "1. 先依据 5m/15m/1H 趋势与均线结构判断方向，仅在多周期共振时考虑顺势建仓。\n"
            "2. 结合 RSI/ATR 判断动量与波动，明确是趋势延续还是反转博弈，量化触发位置（支撑/阻力/区间百分位）。\n"
            "3. 必须引用盘口/成交/资金费率等数据验证买卖力量和流动性，若数据缺失或矛盾要主动说明并降低信心。\n"
            "4. 建仓前给出大致的入场逻辑与触发条件，并确保风险回报≥1:1.5（默认 TP 10% / SL 5% 可微调但要说明理由）。\n"
            "5. 若多空信号冲突、成交量低或波动不足，优先输出 hold，并解释缺乏优势的具体原因。\n"
            "6. 风险描述需落地到具体指标（资金费率、盘口失衡、关键价位被破等），invalid_conditions 要可执行。\n"
            "7. confidence>0.65 仅在逻辑、数据、风险三者一致时给出；否则控制在 0.5 附近以防误导。\n"
        )
        self._system_base = (
            "你是负责数字资产量化交易分析的顾问，需输出明确且审慎的操作建议。"
            "必须返回可解析的 JSON，字段 action 仅能是 buy/sell/hold，confidence 为 0~1 数值，"
            "其余字段为简短中文字符串。数据不足或信号矛盾时默认给出 hold，并在 risk 中说明不确定性。"
            "避免夸张或绝对化措辞，不要输出 Markdown、额外文字或代码块。"
        )
        self._batch_max = batch_max or 4
        self._batch_wait = batch_wait or 0.15
        self._batch_worker = _LLMBatchWorker(self, max_batch=self._batch_max, wait_seconds=self._batch_wait)

    def analyze(
        self,
        inst_id: str,
        timeframe: str,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]] = None,
        snapshot: Optional[MarketSnapshot] = None,
        account_snapshot: Optional[Dict[str, float]] = None,
        risk_note: Optional[str] = None,
        position_entries: Optional[List[Dict[str, Any]]] = None,
        perf_stats: Optional[Dict[str, Any]] = None,
        daily_stats: Optional[Dict[str, Any]] = None,
    ) -> LLMAnalysis:
        """调用 LLM 输出分析文本."""

        latest = features.tail(25)
        latest_ts = str(features.iloc[-1].get("ts", ""))
        cache_key = (inst_id, timeframe)
        cached = self._analysis_cache.get(cache_key)
        if cached and cached[0] == latest_ts:
            return cached[1]
        summary_text = build_market_summary(latest, higher_features, snapshot)
        performance_hint = build_performance_hint(inst_id, timeframe)
        account_context = self._build_account_context(account_snapshot, risk_note)
        position_context = self._build_position_context(inst_id, position_entries)
        pnl_context = self._build_pnl_context(perf_stats, daily_stats)
        payload = self._build_request_payload(
            inst_id=inst_id,
            timeframe=timeframe,
            summary_text=summary_text,
            performance_hint=performance_hint,
            snapshot=snapshot,
            account_context=account_context,
            position_context=position_context,
            pnl_context=pnl_context,
            base_strategy_hint="基础策略：当前仅依赖系统指标与 LLM。"
        )
        if self._batch_worker:
            result = self._batch_worker.submit(payload)
        else:
            result = self._call_single(payload)
        self._store_cache(cache_key, latest_ts, result)
        return result

    def _init_client(self):
        provider = self.provider
        if provider in {
            AIProvider.DEEPSEEK,
            AIProvider.OPENAI,
            AIProvider.MOONSHOT,
            AIProvider.QWEN,
            AIProvider.GROK,
        }:
            api_key, base_url, model = self._resolve_openai_like(provider)
            client = OpenAI(api_key=api_key, base_url=base_url)
            return client, model
        if provider == AIProvider.AZURE_OPENAI:
            if not all(
                [
                    self.ai.azure_api_key,
                    self.ai.azure_endpoint,
                    self.ai.azure_deployment,
                ]
            ):
                raise ValueError("Azure OpenAI 配置不完整。")
            client = AzureOpenAI(
                api_key=self.ai.azure_api_key,
                api_version=self.ai.azure_api_version,
                azure_endpoint=self.ai.azure_endpoint,
            )
            return client, self.ai.azure_deployment
        if provider == AIProvider.ANTHROPIC:
            raise NotImplementedError("Anthropic 集成暂未实现。")
        raise ValueError(f"Unsupported AI provider: {provider}")

    def _resolve_openai_like(self, provider: AIProvider):
        if provider == AIProvider.DEEPSEEK:
            key = self.ai.deepseek_api_key
            url = self.ai.deepseek_base_url
            model = self.ai.deepseek_model
        elif provider == AIProvider.OPENAI:
            key = self.ai.openai_api_key
            url = self.ai.openai_base_url
            model = self.ai.openai_model
        elif provider == AIProvider.MOONSHOT:
            key = self.ai.moonshot_api_key
            url = self.ai.moonshot_base_url
            model = self.ai.moonshot_model
        elif provider == AIProvider.QWEN:
            key = self.ai.qwen_api_key
            url = self.ai.qwen_base_url
            model = self.ai.qwen_model
        elif provider == AIProvider.GROK:
            key = self.ai.grok_api_key
            url = self.ai.grok_base_url
            model = self.ai.grok_model
        else:
            raise ValueError(f"Unsupported provider: {provider}")
        if not key:
            raise ValueError(f"{provider.value} 缺少 API Key")
        return key, url, model

    def _store_cache(self, key: Tuple[str, str], ts: str, value: LLMAnalysis) -> None:
        if not ts or not value:
            return
        with self._cache_lock:
            if key in self._analysis_cache:
                self._analysis_cache.pop(key, None)
            self._analysis_cache[key] = (ts, value)
            if len(self._analysis_cache) > self._cache_limit:
                self._analysis_cache.popitem(last=False)
            self._cache_dirty = True
        self._flush_cache_to_disk()

    def _build_request_payload(
        self,
        inst_id: str,
        timeframe: str,
        summary_text: str,
        performance_hint: str,
        snapshot: Optional[MarketSnapshot],
        account_context: str,
        position_context: str,
        pnl_context: str,
        base_strategy_hint: str,
    ) -> _LLMRequestPayload:
        snapshot_text = _format_snapshot(snapshot)
        request_id = f"{inst_id}-{timeframe}-{int(time.time() * 1_000_000) % 1_000_000}"
        return _LLMRequestPayload(
            request_id=request_id,
            inst_id=inst_id,
            timeframe=timeframe,
            performance_hint=performance_hint,
            snapshot_text=snapshot_text,
            summary_text=summary_text,
            account_context=account_context,
            position_context=position_context,
            pnl_context=pnl_context,
            base_strategy_hint=base_strategy_hint,
        )

    def _build_account_context(
        self,
        account_snapshot: Optional[Dict[str, float]],
        risk_note: Optional[str],
    ) -> str:
        parts: List[str] = []
        equity = None
        available = None
        if account_snapshot is not None:
            raw_equity = account_snapshot.get("equity")
            raw_available = account_snapshot.get("available")
            try:
                equity = float(raw_equity) if raw_equity is not None else None
            except (TypeError, ValueError):
                equity = None
            try:
                available = float(raw_available) if raw_available is not None else None
            except (TypeError, ValueError):
                available = None
        if equity is not None and equity > 0:
            ratio = (available or 0.0) / equity if available is not None else None
            if available is not None:
                parts.append(f"权益 {equity:.2f} USD，可用 {available:.2f} USD ({(ratio or 0.0) * 100:.0f}%)")
            else:
                parts.append(f"权益 {equity:.2f} USD，可用资金未知")
        elif available is not None:
            parts.append(f"可用资金 {available:.2f} USD，权益未知")
        else:
            parts.append("账户资金数据不可用")
        strategy = getattr(self.settings, "strategy", None)
        if strategy:
            usage = getattr(strategy, "balance_usage_ratio", None)
            leverage = getattr(strategy, "default_leverage", None)
            tp = getattr(strategy, "default_take_profit_pct", None)
            sl = getattr(strategy, "default_stop_loss_pct", None)
            details: List[str] = []
            if usage:
                details.append(f"单轮使用 {usage * 100:.0f}% 资金")
            if leverage:
                details.append(f"策略杠杆 {leverage:.2f}x")
            if tp and sl:
                details.append(f"默认 TP {tp:.2%} / SL {sl:.2%}")
            elif tp:
                details.append(f"默认 TP {tp:.2%}")
            elif sl:
                details.append(f"默认 SL {sl:.2%}")
            if details:
                parts.append("；".join(details))
        if risk_note:
            parts.append(risk_note)
        return "资金与风控：" + "；".join(parts)

    def _build_system_prompt(self, account_context: str, pnl_context: str) -> str:
        return (
            f"{self._system_base}\n"
            f"{account_context}\n"
            f"{pnl_context}\n"
        )

    def _build_position_context(
        self,
        inst_id: str,
        position_entries: Optional[List[Dict[str, Any]]],
    ) -> str:
        if not position_entries:
            return f"持仓：{inst_id} 当前无持仓。"
        fragments: List[str] = []
        for entry in position_entries:
            try:
                raw_size = float(entry.get("pos") or 0.0)
            except (TypeError, ValueError):
                raw_size = 0.0
            if abs(raw_size) <= 0:
                continue
            pos_side = entry.get("posSide") or ("long" if raw_size > 0 else "short")
            avg_px = entry.get("avgPx") or entry.get("avgPxUsd") or "-"
            mark_px = entry.get("markPx") or entry.get("last") or "-"
            upl = entry.get("upl") or entry.get("uplVal") or "0"
            upl_ratio = entry.get("uplRatio") or entry.get("uplRatioP") or "0"
            try:
                upl_ratio_val = float(upl_ratio)
                if abs(upl_ratio_val) > 5:
                    upl_ratio_val /= 100
                upl_ratio_text = f"{upl_ratio_val:.2%}"
            except (TypeError, ValueError):
                upl_ratio_text = str(upl_ratio)
            margin_mode = entry.get("mgnMode") or entry.get("marginMode") or "-"
            lever = entry.get("lever") or entry.get("leverType") or "-"
            fragments.append(
                f"{pos_side} {raw_size} 张，均价 {avg_px}，标记 {mark_px}，浮盈 {upl} ({upl_ratio_text})，杠杆 {lever}，保证金 {margin_mode}"
            )
        if not fragments:
            return f"持仓：{inst_id} 当前无持仓。"
        return f"持仓：{inst_id} " + "；".join(fragments)

    @staticmethod
    def _build_pnl_context(
        perf_stats: Optional[Dict[str, Any]],
        daily_stats: Optional[Dict[str, Any]],
    ) -> str:
        parts: List[str] = []
        if perf_stats:
            lookback = int(perf_stats.get("lookback_days", 0) or 0)
            pnl = perf_stats.get("total_pnl", 0.0) or 0.0
            win_rate = (perf_stats.get("win_rate") or 0.0) * 100
            sample = int(perf_stats.get("sample_count", 0) or 0)
            parts.append(
                f"近{lookback}日 P/L {pnl:+.2f} USDT，胜率 {win_rate:.0f}% ，样本 {sample}"
            )
        if daily_stats:
            day_pnl = daily_stats.get("total_pnl", 0.0) or 0.0
            day_win = (daily_stats.get("win_rate") or 0.0) * 100
            day_sample = int(daily_stats.get("sample_count", 0) or 0)
            parts.append(f"当日 P/L {day_pnl:+.2f} USDT，胜率 {day_win:.0f}% ，样本 {day_sample}")
        if not parts:
            return "近期 P/L：暂无可用统计。"
        return "近期 P/L：" + "；".join(parts)

    def _call_single(self, payload: _LLMRequestPayload) -> LLMAnalysis:
        user_prompt = self._compose_single_prompt(payload)
        system_prompt = self._build_system_prompt(payload.account_context, payload.pnl_context)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        analysis_text = (response.choices[0].message.content or "").strip()
        return LLMAnalysis(
            text=analysis_text,
            summary=payload.summary_text,
            history_hint=payload.performance_hint,
        )

    def _call_batch(self, payloads: List[_LLMRequestPayload]) -> Dict[str, LLMAnalysis]:
        if not payloads:
            return {}
        user_prompt = self._compose_batch_prompt(payloads)
        sys_prompt = self._build_system_prompt(payloads[0].account_context, payloads[0].pnl_context)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": sys_prompt,
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        text = (response.choices[0].message.content or "").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM 批量返回无法解析: {text}") from exc
        if not isinstance(data, list):
            raise ValueError("LLM 批量返回的根节点必须是数组。")
        mapping: Dict[str, LLMAnalysis] = {}
        for obj in data:
            if not isinstance(obj, dict):
                continue
            request_id = str(obj.get("request_id") or "")
            if not request_id:
                continue
            analysis = LLMAnalysis(
                text=json.dumps(obj, ensure_ascii=False),
                summary="",
                history_hint="",
            )
            mapping[request_id] = analysis
        # 填充 summary/history_hint
        for payload in payloads:
            result = mapping.get(payload.request_id)
            if result:
                result.summary = payload.summary_text
                result.history_hint = payload.performance_hint
        return mapping

    def _load_cache_from_disk(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            with self._cache_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return
        for entry in payload:
            try:
                key = (entry["inst_id"], entry["timeframe"])
                ts = entry.get("ts", "")
                analysis_data = entry.get("analysis") or {}
                analysis = LLMAnalysis(
                    text=analysis_data.get("text", ""),
                    summary=analysis_data.get("summary", ""),
                    history_hint=analysis_data.get("history_hint", ""),
                )
                if ts and key not in self._analysis_cache:
                    self._analysis_cache[key] = (ts, analysis)
            except Exception:
                continue
        while len(self._analysis_cache) > self._cache_limit:
            self._analysis_cache.popitem(last=False)

    def _flush_cache_to_disk(self, force: bool = False) -> None:
        now = time.time()
        if not force:
            if not self._cache_dirty:
                return
            if now - self._last_cache_flush < self._cache_flush_interval:
                return
        with self._cache_lock:
            serializable = [
                {
                    "inst_id": key[0],
                    "timeframe": key[1],
                    "ts": ts,
                    "analysis": {
                        "text": analysis.text,
                        "summary": analysis.summary,
                        "history_hint": analysis.history_hint,
                    },
                }
                for key, (ts, analysis) in self._analysis_cache.items()
            ]
        try:
            with self._cache_path.open("w", encoding="utf-8") as fh:
                json.dump(serializable, fh, ensure_ascii=False, indent=2)
        except Exception:
            logger.warning("LLM 缓存写入失败", exc_info=True)
        else:
            self._last_cache_flush = now
            self._cache_dirty = False

    def _flush_cache_on_exit(self) -> None:
        try:
            self._flush_cache_to_disk(force=True)
        except Exception:
            logger.warning("退出时写入 LLM 缓存失败", exc_info=True)

    def _compose_single_prompt(self, payload: _LLMRequestPayload) -> str:
        return (
            f"交易对: {payload.inst_id}\n"
            f"周期: {payload.timeframe}\n"
            f"{payload.performance_hint}\n"
            f"{payload.position_context}\n"
            f"{payload.base_strategy_hint}\n"
            f"市场快照：\n{payload.snapshot_text}\n"
            "以下为系统生成的多尺度行情摘要：\n"
            f"{payload.summary_text}\n"
            f"{self._analysis_guidance}"
            "请严格输出 JSON，结构为 "
            '{"action":"buy/sell/hold","confidence":0.0-1.0,"reason":"简要逻辑","risk":"主要风险",'
            '"time_horizon":"建议适用周期","invalid_conditions":"信号失效条件"}，'
            "不得输出额外文字。"
        )

    def _compose_batch_prompt(self, payloads: List[_LLMRequestPayload]) -> str:
        sections = []
        for idx, payload in enumerate(payloads, start=1):
            sections.append(
                f"[{idx}] request_id: {payload.request_id}\n"
                f"交易对: {payload.inst_id}\n"
                f"周期: {payload.timeframe}\n"
                f"{payload.performance_hint}\n"
                f"{payload.position_context}\n"
                f"{payload.base_strategy_hint}\n"
                f"市场快照：\n{payload.snapshot_text}\n"
                f"行情摘要：\n{payload.summary_text}\n"
            )
        instruction = (
            f"以下共有 {len(payloads)} 个交易对需要分析。\n"
            "请返回 JSON 数组，数组中的元素顺序必须与输入一致，"
            "每个元素都包含字段 "
            '{"request_id","action","confidence","reason","risk","time_horizon","invalid_conditions"}，'
            "action 仅能为 buy/sell/hold，confidence 为 0~1 小数。"
        )
        return (
            f"{instruction}\n"
            f"{self._analysis_guidance}"
            + "\n".join(sections)
        )


EVAL_LOG_PATH = Path("logs/llm-decisions.jsonl")


@dataclass
class DecisionRecord:
    timestamp: str
    inst_id: str
    timeframe: str
    summary: str
    llm_action: str
    llm_confidence: float
    llm_reason: str
    strategy_action: str
    close_price: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "inst_id": self.inst_id,
            "timeframe": self.timeframe,
            "summary": self.summary,
            "llm_action": self.llm_action,
            "llm_confidence": self.llm_confidence,
            "llm_reason": self.llm_reason,
            "strategy_action": self.strategy_action,
            "close_price": self.close_price,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False)


class DecisionLogger:
    def __init__(self, path: Path = EVAL_LOG_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: DecisionRecord) -> None:
        payload = record.as_dict()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        _register_performance_record(payload)


def _load_records(path: Path = EVAL_LOG_PATH) -> list[Dict]:
    if not path.exists():
        return []
    entries: list[Dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.min


def build_performance_hint(inst_id: str, timeframe: str, window: int = 30) -> str:
    _ensure_performance_cache_loaded()
    key = (inst_id, timeframe)
    with _performance_cache_lock:
        cached = list(_performance_cache.get(key, ()))
    if not cached:
        return "历史表现：暂无可用决策记录。"
    records = cached[-(window + 1) :]
    if len(records) < 2:
        return "历史表现：暂无足够数据。"
    records = sorted(records, key=lambda rec: _parse_ts(str(rec.get("timestamp") or "")))
    stats: Dict[str, Dict[str, float]] = {}
    for idx in range(len(records) - 1):
        current = records[idx]
        nxt = records[idx + 1]
        action = (current.get("llm_action") or "").lower()
        if action not in ("buy", "sell"):
            continue
        curr_price = float(current.get("close_price") or 0.0)
        next_price = float(nxt.get("close_price") or 0.0)
        if curr_price <= 0 or next_price <= 0:
            continue
        direction = 1 if action == "buy" else -1
        move = (next_price - curr_price) * direction
        bucket = stats.setdefault(action, {"total": 0, "wins": 0})
        bucket["total"] += 1
        if move > 0:
            bucket["wins"] += 1
    if not stats:
        return "历史表现：暂无足够数据。"
    parts = []
    for action, result in stats.items():
        total = int(result.get("total", 0))
        wins = int(result.get("wins", 0))
        if total <= 0:
            continue
        win_rate = wins / total
        parts.append(f"{action.upper()} 胜率 {win_rate:.0%} ({wins}/{total})")
    if not parts:
        return "历史表现：暂无足够数据。"
    return "历史表现：" + "；".join(parts)


def _format_snapshot(snapshot: Optional[MarketSnapshot]) -> str:
    if not snapshot:
        return "暂无盘口、成交与衍生品数据。"
    parts: list[str] = []
    order_book = snapshot.order_book
    if order_book:
        parts.append(
            f"盘口: spread={order_book.spread_pct:.2%}, imbalance={order_book.imbalance:+.2f}, "
            f"买一={order_book.top_bid:.4f}, 卖一={order_book.top_ask:.4f}"
        )
    trades = snapshot.trades
    if trades:
        parts.append(
            f"成交: 买量占比={trades.buy_ratio:.2%}, 均笔={trades.avg_size:.4f}, 次数={trades.count}"
        )
    derivatives = snapshot.derivatives
    if derivatives:
        fr = f"{derivatives.funding_rate:.4%}" if derivatives.funding_rate is not None else "n/a"
        oi = f"{derivatives.open_interest:.4f}" if derivatives.open_interest is not None else "n/a"
        parts.append(f"衍生品: 资金费率={fr}, 持仓量={oi}")
    if not parts:
        return "暂无盘口、成交与衍生品数据。"
    return "\n".join(parts)


class _LLMBatchWorker:
    def __init__(
        self,
        service: "LLMService",
        max_batch: Optional[int] = None,
        wait_seconds: Optional[float] = None,
    ) -> None:
        self.service = service
        self.max_batch = max_batch or 4
        self.wait_seconds = wait_seconds or 0.15
        self._queue: "queue.Queue[Tuple[_LLMRequestPayload, Future]]" = queue.Queue()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, payload: _LLMRequestPayload) -> LLMAnalysis:
        future: Future = Future()
        self._queue.put((payload, future))
        return future.result()

    def _run(self) -> None:
        while True:
            payload, future = self._queue.get()
            batch: List[Tuple[_LLMRequestPayload, Future]] = [(payload, future)]
            start = time.time()
            while len(batch) < self.max_batch:
                remaining = self.wait_seconds - (time.time() - start)
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            self._process_batch(batch)

    def _process_batch(self, batch: List[Tuple[_LLMRequestPayload, Future]]) -> None:
        payloads = [item[0] for item in batch]
        try:
            results = self.service._call_batch(payloads)
        except Exception as exc:
            logger.warning(f"LLM 批量请求失败，回退单次调用: {exc}")
            for payload, future in batch:
                try:
                    future.set_result(self.service._call_single(payload))
                except Exception as inner:
                    future.set_exception(inner)
            return
        for payload, future in batch:
            result = results.get(payload.request_id)
            if result is None:
                try:
                    result = self.service._call_single(payload)
                except Exception as inner:
                    future.set_exception(inner)
                    continue
            future.set_result(result)


__all__ = ["LLMService", "LLMAnalysis", "DecisionLogger", "DecisionRecord", "build_performance_hint"]
