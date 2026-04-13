"""REST 重试与错误分类测试。"""

from __future__ import annotations

from okx.api import algotrade as algo_api

from core.client.rest import OKXClient


def test_classify_error_code() -> None:
    assert OKXClient._classify_error_code("50011") == "rate_limit"
    assert OKXClient._classify_error_code("50100") == "auth"
    assert OKXClient._classify_error_code("51008") == "business"
    assert OKXClient._classify_error_code("50040") == "transient"


def test_request_retries_on_rate_limit(monkeypatch) -> None:
    client = object.__new__(OKXClient)
    client._max_retries = 2
    client._retry_backoff = 0.0
    monkeypatch.setattr("core.client.rest.time.sleep", lambda _s: None)
    called = {"n": 0}

    def _fake_call():
        called["n"] += 1
        if called["n"] == 1:
            return {"code": "50011", "msg": "too many requests", "data": []}
        return {"code": "0", "data": [{"ok": True}]}

    result = OKXClient._request(client, "x", _fake_call)

    assert called["n"] == 2
    assert "error" not in result


def test_cancel_algo_orders_passes_proxy_host_and_payload() -> None:
    client = object.__new__(OKXClient)
    calls = []

    class _Algo:
        proxy_host = "https://proxy.example"

        def send_request(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"code": "0", "data": []}

    client._algo = _Algo()
    client._max_retries = 0
    client._retry_backoff = 0.0

    OKXClient.cancel_algo_orders(
        client,
        [
            {"algoId": "a1", "instId": "BTC-USDT-SWAP"},
            {"algoId": "a2", "instId": "ETH-USDT-SWAP"},
        ],
    )

    assert calls == [
        (
            (
                algo_api._AlgoTradeEndpoints.set_cancel_algos[0],
                algo_api._AlgoTradeEndpoints.set_cancel_algos[1],
                [
                    {"algoId": "a1", "instId": "BTC-USDT-SWAP"},
                    {"algoId": "a2", "instId": "ETH-USDT-SWAP"},
                ],
            ),
            {"proxy_host": "https://proxy.example"},
        )
    ]
