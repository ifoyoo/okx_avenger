"""OKX REST API 客户端封装."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Type, TypeVar

from loguru import logger
from okx.api import account as account_api
from okx.api import market as market_api
from okx.api import public as public_api
from okx.api import trade as trade_api
from okx.api._client import Client as _Client
from okx.api import algotrade as algo_api

from config.settings import AppSettings, get_settings

ApiClient = TypeVar("ApiClient", bound=_Client)


class OKXClient:
    """最常用的 REST 接口封装，基于官方 okx SDK."""

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.account = self.settings.account
        self._base_url = self.account.okx_base_url.rstrip("/")
        self._flag = "0"
        self._max_retries = max(0, int(getattr(self.account, "http_max_retries", 2) or 2))
        self._retry_backoff = max(0.05, float(getattr(self.account, "http_retry_backoff_seconds", 0.4) or 0.4))
        proxies = self._build_proxies(self.account.http_proxy)
        self._market = self._create_api_client(market_api.Market, proxies)
        self._trade = self._create_api_client(trade_api.Trade, proxies)
        self._account = self._create_api_client(account_api.Account, proxies)
        self._public = self._create_api_client(public_api.Public, proxies)
        self._algo = self._create_api_client(algo_api.AlgoTrade, proxies)

    def _create_api_client(self, cls: Type[ApiClient], proxies: Dict[str, str]) -> ApiClient:
        client = cls(
            key=self.account.okx_api_key,
            secret=self.account.okx_api_secret,
            passphrase=self.account.okx_passphrase,
            flag=self._flag,
            proxies=proxies,
        )
        client.API_URL = self._base_url
        return client

    @staticmethod
    def _build_proxies(proxy_url: Optional[str]) -> Dict[str, str]:
        if not proxy_url:
            return {}
        return {"http": proxy_url, "https": proxy_url}

    @staticmethod
    def _ensure_success(response: Dict[str, Any]) -> Dict[str, Any]:
        code = str(response.get("code", "0"))
        if code in ("0", "200"):
            return response
        msg = response.get("msg", "")
        logger.error(f"OKX 接口错误: code={code} msg={msg}")
        response["error"] = {
            "code": code,
            "message": msg,
            "data": response.get("data"),
        }
        return response

    @staticmethod
    def _classify_error_code(code: str) -> str:
        text = str(code or "").strip()
        if text in {"50100", "50101", "50113", "50114"}:
            return "auth"
        if text in {"50011", "50061"}:
            return "rate_limit"
        if text.startswith("500"):
            return "transient"
        if text in {"0", "200", ""}:
            return "none"
        return "business"

    @staticmethod
    def _classify_exception(exc: Exception) -> str:
        text = str(exc or "").lower()
        if "timeout" in text:
            return "timeout"
        if "connection" in text or "network" in text or "dns" in text:
            return "network"
        return "unknown"

    def _request(self, name: str, fn, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        attempts = max(1, self._max_retries + 1)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            attempt_no = attempt + 1
            try:
                response = fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                category = self._classify_exception(exc)
                if attempt_no < attempts:
                    sleep_s = self._retry_backoff * (2 ** attempt)
                    logger.warning(
                        "event=okx_retry name={} attempt={}/{} category={} sleep_s={:.2f}",
                        name,
                        attempt_no,
                        attempts,
                        category,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                raise
            normalized = self._ensure_success(response)
            error = normalized.get("error")
            if not isinstance(error, dict):
                return normalized
            code = str(error.get("code") or "")
            category = self._classify_error_code(code)
            normalized["error"]["category"] = category
            if category in {"rate_limit", "transient"} and attempt_no < attempts:
                sleep_s = self._retry_backoff * (2 ** attempt)
                logger.warning(
                    "event=okx_retry name={} attempt={}/{} code={} category={} sleep_s={:.2f}",
                    name,
                    attempt_no,
                    attempts,
                    code,
                    category,
                    sleep_s,
                )
                time.sleep(sleep_s)
                continue
            return normalized
        if last_exc:
            raise last_exc
        return {"error": {"code": "UNKNOWN", "message": "request failed", "category": "unknown"}}

    def get_account_balance(self, ccy: Optional[str] = None) -> Dict[str, Any]:
        """查询账户余额."""

        return self._request("account_balance", self._account.get_balance, ccy=ccy or "")

    def get_ticker(self, inst_id: str) -> Dict[str, Any]:
        """获取单个交易对行情."""

        return self._request("ticker", self._market.get_ticker, instId=inst_id)

    def get_tickers(self, inst_type: str = "SWAP") -> Dict[str, Any]:
        """批量获取某类合约的 tickers."""

        return self._request("tickers", self._market.get_tickers, instType=inst_type)

    def get_order_book(self, inst_id: str, depth: int = 5) -> Dict[str, Any]:
        """获取盘口深度."""

        return self._request("order_book", self._market.get_books, instId=inst_id, sz=str(depth))

    def get_trades(self, inst_id: str, limit: int = 20) -> Dict[str, Any]:
        """获取最近成交列表."""

        return self._request("trades", self._market.get_trades, instId=inst_id, limit=str(limit) if limit else "")

    def get_funding_rate(self, inst_id: str) -> Dict[str, Any]:
        """获取永续合约资金费率."""

        return self._request("funding_rate", self._public.get_funding_rate, instId=inst_id)

    def get_open_interest(self, inst_id: str) -> Dict[str, Any]:
        """获取合约持仓量."""

        return self._request("open_interest", self._public.get_open_interest, instId=inst_id)

    def get_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        after: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """K线数据."""

        return self._request(
            "candles",
            self._market.get_candles,
            instId=inst_id,
            bar=bar,
            after=after or "",
            before=before or "",
            limit=str(limit) if limit else "",
        )

    def get_trade_fills(
        self,
        inst_type: str = "SWAP",
        begin: Optional[str] = None,
        end: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """获取近 3 天的成交明细."""

        return self._request(
            "trade_fills",
            self._trade.get_fills,
            instType=inst_type or "",
            begin=begin or "",
            end=end or "",
            after=after or "",
            limit=str(limit),
        )

    def get_trade_fills_history(
        self,
        inst_type: str = "SWAP",
        begin: Optional[str] = None,
        end: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """获取近 3 个月的成交明细."""

        return self._request(
            "trade_fills_history",
            self._trade.get_fills_history,
            instType=inst_type,
            begin=begin or "",
            end=end or "",
            after=after or "",
            limit=str(limit),
        )

    def place_order(
        self,
        inst_id: str,
        td_mode: str,
        side: str,
        ord_type: str,
        sz: str,
        px: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
        pos_side: Optional[str] = None,
        tp_trigger_px: Optional[str] = None,
        tp_trigger_px_type: Optional[str] = None,
        tp_order_px: Optional[str] = None,
        sl_trigger_px: Optional[str] = None,
        sl_trigger_px_type: Optional[str] = None,
        sl_order_px: Optional[str] = None,
        attach_algo_ords: Optional[List[Dict[str, Any]]] = None,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """下单，支持市价/限价."""
        resolved_cl_ord_id = str(cl_ord_id or "").strip()
        if not resolved_cl_ord_id:
            resolved_cl_ord_id = f"auto{uuid.uuid4().hex[:24]}"

        payload: Dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
            "px": px or "",
            "clOrdId": resolved_cl_ord_id,
            "posSide": pos_side or "",
            "tpTriggerPx": tp_trigger_px or "",
            "tpTriggerPxType": tp_trigger_px_type or "",
            "tpOrdPx": tp_order_px or "",
            "slTriggerPx": sl_trigger_px or "",
            "slTriggerPxType": sl_trigger_px_type or "",
            "slOrdPx": sl_order_px or "",
            "reduceOnly": reduce_only,
        }
        if attach_algo_ords:
            payload["attachAlgoOrds"] = attach_algo_ords
        payload["proxy_host"] = getattr(self._trade, "proxy_host", None)
        return self._request(
            "place_order",
            self._trade.send_request,
            *trade_api._TradeEndpoints.set_order,
            **payload,
        )

    def cancel_order(self, inst_id: str, ord_id: Optional[str] = None, cl_ord_id: Optional[str] = None) -> Dict[str, Any]:
        """撤单."""

        return self._request(
            "cancel_order",
            self._trade.set_cancel_order,
            instId=inst_id,
            ordId=ord_id or "",
            clOrdId=cl_ord_id or "",
        )

    def instruments(self, inst_type: str = "SWAP") -> Dict[str, Any]:
        """查询支持的合约或现货品种."""

        return self._request("instruments", self._public.get_instruments, instType=inst_type)

    def get_account_config(self) -> Dict[str, Any]:
        """查看账户配置."""

        return self._request("account_config", self._account.get_config)

    def get_positions(self, inst_type: str = "SWAP") -> Dict[str, Any]:
        return self._request("positions", self._account.get_positions, instType=inst_type)

    def list_conditional_algos(self, inst_id: Optional[str] = None) -> List[Dict[str, Any]]:
        inst_type = self._infer_inst_type(inst_id) if inst_id else ""
        try:
            resp = self._algo.get_orders_algo_pending(
                ordType="conditional",
                instType=inst_type,
                instId=inst_id or "",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"查询策略委托失败 inst={inst_id} err={exc}")
            return []
        return resp.get("data") or []

    def cancel_algo_orders(self, entries: Sequence[Dict[str, str]]) -> None:
        payload = []
        for entry in entries:
            algo_id = entry.get("algoId") if entry else None
            inst_id = entry.get("instId") if entry else None
            if not algo_id or not inst_id:
                continue
            payload.append({"algoId": str(algo_id), "instId": str(inst_id)})
        if not payload:
            return
        try:
            self._algo.send_request(*algo_api._AlgoTradeEndpoints.set_cancel_algos, payload)
            logger.info(
                "Cancelled {} stale algo orders: {}", len(payload), ", ".join(item["algoId"] for item in payload)
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"撤销旧策略委托失败 payload={payload} err={exc}")

    @staticmethod
    def _infer_inst_type(inst_id: Optional[str]) -> str:
        if not inst_id:
            return ""
        inst = inst_id.upper()
        if inst.endswith("-SWAP"):
            return "SWAP"
        if inst.endswith("-FUTURES"):
            return "FUTURES"
        if inst.endswith("-OPTION"):
            return "OPTION"
        return "SPOT"

    def close(self) -> None:
        """官方 SDK 使用 requests，会在 GC 时释放连接."""

        # SDK 暂无显式 close 接口，预留占位方法利于兼容旧调用。
        return None


__all__ = ["OKXClient"]
