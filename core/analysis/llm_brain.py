"""LLM 分析大脑（可选）：为策略融合提供结构化观点。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd
import requests
from loguru import logger

from core.models import SignalAction


@dataclass
class BrainDecision:
    action: SignalAction
    confidence: float
    reason: str = ""
    risk: str = ""
    time_horizon: str = ""
    invalid_conditions: str = ""
    provider: str = "llm"
    model: str = ""
    latency_ms: float = 0.0
    quality_score: float = 0.0
    raw_text: str = ""

    def to_analysis_json(self) -> str:
        payload = {
            "action": self.action.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "risk": self.risk,
            "time_horizon": self.time_horizon,
            "invalid_conditions": self.invalid_conditions,
        }
        return json.dumps(payload, ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        return data


def _extract_json_blob(text: str) -> Optional[Dict[str, Any]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned, flags=re.IGNORECASE)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    match = re.search(r"(\{[\s\S]*\})", cleaned)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _normalize_action(value: Any) -> SignalAction:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "做多", "多", "bull"}:
        return SignalAction.BUY
    if text in {"sell", "short", "做空", "空", "bear"}:
        return SignalAction.SELL
    return SignalAction.HOLD


def _normalize_confidence(value: Any) -> float:
    try:
        return max(0.1, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _score_decision_quality(parsed: Dict[str, Any], raw_text: str) -> float:
    score = 0.0
    action = str(parsed.get("action") or "").strip().lower()
    if action in {"buy", "sell", "hold", "long", "short"}:
        score += 0.35
    confidence = parsed.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = -1.0
    if 0.0 <= confidence_value <= 1.0:
        score += 0.25
    reason = str(parsed.get("reason") or "").strip()
    if len(reason) >= 6:
        score += 0.2
    risk = str(parsed.get("risk") or "").strip()
    if risk:
        score += 0.1
    if str(parsed.get("time_horizon") or parsed.get("horizon") or "").strip():
        score += 0.05
    if len((raw_text or "").strip()) >= 20:
        score += 0.05
    return max(0.0, min(1.0, score))


class LLMBrain:
    """OpenAI 兼容接口的 LLM 决策组件。"""

    def __init__(self, settings: Any) -> None:
        self.enabled = bool(getattr(settings, "enabled", False))
        self.provider = str(getattr(settings, "provider", "openai_compatible") or "openai_compatible")
        self.api_base = str(getattr(settings, "api_base", "https://api.openai.com/v1") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = str(getattr(settings, "api_key", "") or "")
        self.model = str(getattr(settings, "model", "gpt-4o-mini") or "gpt-4o-mini")
        self.timeout_seconds = float(getattr(settings, "timeout_seconds", 8.0) or 8.0)
        self.temperature = float(getattr(settings, "temperature", 0.1) or 0.1)
        self.max_tokens = int(getattr(settings, "max_tokens", 320) or 320)
        self.min_quality_score = max(0.0, min(1.0, float(getattr(settings, "min_quality_score", 0.45) or 0.45)))
        self.reject_missing_reason = bool(getattr(settings, "reject_missing_reason", True))

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.api_key)

    def analyze(
        self,
        *,
        inst_id: str,
        timeframe: str,
        features: pd.DataFrame,
        higher_features: Optional[Dict[str, pd.DataFrame]],
        deterministic_summary: str,
        deterministic_analysis: str,
        risk_note: Optional[str],
        account_snapshot: Optional[Dict[str, float]],
        market_intel: Optional[Dict[str, Any]] = None,
    ) -> Optional[BrainDecision]:
        if not self.ready:
            return None
        latest = features.iloc[-1]
        close = float(latest.get("close", 0.0) or 0.0)
        rsi = float(latest.get("rsi", 50.0) or 50.0)
        atr = float(latest.get("atr", 0.0) or 0.0)
        ema_fast = float(latest.get("ema_fast", close) or close)
        ema_slow = float(latest.get("ema_slow", close) or close)
        atr_pct = (atr / close) if close > 0 else 0.0
        higher_hint = []
        if higher_features:
            for tf, df in higher_features.items():
                if df is None or df.empty:
                    continue
                node = df.iloc[-1]
                higher_hint.append(
                    f"{tf}: close={float(node.get('close', 0.0) or 0.0):.4f}, "
                    f"rsi={float(node.get('rsi', 50.0) or 50.0):.1f}, "
                    f"ema_fast={float(node.get('ema_fast', 0.0) or 0.0):.4f}, "
                    f"ema_slow={float(node.get('ema_slow', 0.0) or 0.0):.4f}"
                )
        account_text = ""
        if account_snapshot:
            eq = float(account_snapshot.get("equity") or 0.0)
            av = float(account_snapshot.get("available") or 0.0)
            pct = (av / eq) if eq > 0 else 0.0
            account_text = f"equity={eq:.2f}, available={av:.2f}, available_pct={pct:.2%}"
        prompt = (
            "你是加密交易风险顾问。请根据输入数据输出严格 JSON，字段为："
            "action(buy/sell/hold), confidence(0-1), reason, risk, time_horizon, invalid_conditions。"
            "禁止输出任何额外字段和自然语言段落。\n\n"
            f"inst_id={inst_id}\n"
            f"timeframe={timeframe}\n"
            f"latest: close={close:.6f}, rsi={rsi:.2f}, atr_pct={atr_pct:.2%}, ema_fast={ema_fast:.6f}, ema_slow={ema_slow:.6f}\n"
            f"higher: {' | '.join(higher_hint) if higher_hint else '-'}\n"
            f"risk_note={risk_note or '-'}\n"
            f"account={account_text or '-'}\n\n"
            f"market_intel={json.dumps(market_intel or {}, ensure_ascii=False)[:1800]}\n\n"
            f"deterministic_summary:\n{deterministic_summary[:1200]}\n\n"
            f"deterministic_analysis:\n{deterministic_analysis[:1600]}\n"
        )
        started = time.time()
        content = self._chat(prompt)
        latency_ms = (time.time() - started) * 1000.0
        if not content:
            return None
        parsed = _extract_json_blob(content)
        if not parsed:
            logger.warning("LLMBrain 返回非 JSON，已忽略。content={}", content[:240])
            return None
        quality_score = _score_decision_quality(parsed, content)
        reason_text = str(parsed.get("reason") or "").strip()
        if self.reject_missing_reason and not reason_text:
            logger.warning("LLMBrain 输出缺少 reason，已拒绝。quality={:.2f}", quality_score)
            return None
        if quality_score < self.min_quality_score:
            logger.warning(
                "LLMBrain 输出质量过低 quality={:.2f} < {:.2f}，已拒绝。",
                quality_score,
                self.min_quality_score,
            )
            return None
        decision = BrainDecision(
            action=_normalize_action(parsed.get("action")),
            confidence=_normalize_confidence(parsed.get("confidence")),
            reason=reason_text,
            risk=str(parsed.get("risk") or "").strip(),
            time_horizon=str(parsed.get("time_horizon") or parsed.get("horizon") or "").strip(),
            invalid_conditions=str(
                parsed.get("invalid_conditions")
                or parsed.get("invalid_condition")
                or parsed.get("invalid")
                or ""
            ).strip(),
            provider=self.provider,
            model=self.model,
            latency_ms=latency_ms,
            quality_score=quality_score,
            raw_text=content[:2000],
        )
        return decision

    def _chat(self, user_prompt: str) -> Optional[str]:
        endpoint = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是量化交易系统的分析大脑，只返回 JSON。"
                        "action 只能是 buy/sell/hold。confidence 范围 0~1。"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            body = resp.json()
            choices = body.get("choices") or []
            if not choices:
                return None
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
                return "\n".join(part for part in parts if part).strip() or None
            return None
        except Exception as exc:  # pragma: no cover
            logger.warning("LLMBrain 请求失败: {}", exc)
            return None


def build_llm_brain(app_settings: Any) -> Optional[LLMBrain]:
    llm_settings = getattr(app_settings, "llm", None)
    if llm_settings is None:
        return None
    brain = LLMBrain(llm_settings)
    if not brain.enabled:
        return None
    if not brain.api_key:
        logger.warning("LLM 已启用但未配置 LLM_API_KEY，已回退确定性分析。")
        return None
    return brain


__all__ = [
    "BrainDecision",
    "LLMBrain",
    "build_llm_brain",
    "_extract_json_blob",
    "_score_decision_quality",
]
