"""LLM 分析大脑测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from core.analysis.llm_brain import LLMBrain, _extract_json_blob, _score_decision_quality
from core.models import SignalAction


def test_extract_json_blob_fenced() -> None:
    text = "```json\n{\"action\":\"buy\",\"confidence\":0.8}\n```"
    parsed = _extract_json_blob(text)
    assert isinstance(parsed, dict)
    assert parsed["action"] == "buy"
    assert parsed["confidence"] == 0.8


def test_llm_brain_analyze_success(monkeypatch) -> None:
    settings = SimpleNamespace(
        enabled=True,
        provider="openai_compatible",
        api_base="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=3.0,
        temperature=0.1,
        max_tokens=128,
    )
    brain = LLMBrain(settings)

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"sell","confidence":0.73,"reason":"risk up","risk":"vol high"}'
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("core.analysis.llm_brain.requests.post", _fake_post)

    features = pd.DataFrame(
        [
            {
                "close": 100.0,
                "rsi": 54.0,
                "atr": 1.5,
                "ema_fast": 101.0,
                "ema_slow": 99.0,
            }
        ]
    )

    decision = brain.analyze(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        features=features,
        higher_features=None,
        deterministic_summary="summary",
        deterministic_analysis="analysis",
        risk_note=None,
        account_snapshot={"equity": 1000.0, "available": 600.0},
    )

    assert decision is not None
    assert decision.action == SignalAction.SELL
    assert decision.confidence == 0.73
    assert "risk up" in decision.reason


def test_score_decision_quality() -> None:
    score = _score_decision_quality(
        {
            "action": "buy",
            "confidence": 0.7,
            "reason": "trend up",
            "risk": "volatility",
            "time_horizon": "4h",
        },
        '{"action":"buy","confidence":0.7}',
    )
    assert 0.6 <= score <= 1.0


def test_llm_brain_rejects_missing_reason(monkeypatch) -> None:
    settings = SimpleNamespace(
        enabled=True,
        provider="openai_compatible",
        api_base="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=3.0,
        temperature=0.1,
        max_tokens=128,
        min_quality_score=0.4,
        reject_missing_reason=True,
    )
    brain = LLMBrain(settings)

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"buy","confidence":0.8,"risk":"vol high"}'
                        }
                    }
                ]
            }

    monkeypatch.setattr("core.analysis.llm_brain.requests.post", lambda *args, **kwargs: _Resp())
    features = pd.DataFrame([{"close": 100.0, "rsi": 54.0, "atr": 1.5, "ema_fast": 101.0, "ema_slow": 99.0}])

    decision = brain.analyze(
        inst_id="BTC-USDT-SWAP",
        timeframe="5m",
        features=features,
        higher_features=None,
        deterministic_summary="summary",
        deterministic_analysis="analysis",
        risk_note=None,
        account_snapshot={"equity": 1000.0, "available": 600.0},
    )
    assert decision is None
