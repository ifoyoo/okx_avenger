"""OKX REST API 客户端封装."""

from __future__ import annotations

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

    def get_account_balance(self, ccy: Optional[str] = None) -> Dict[str, Any]:
        """查询账户余额."""

        resp = self._account.get_balance(ccy=ccy or "")
        return self._ensure_success(resp)

    def get_ticker(self, inst_id: str) -> Dict[str, Any]:
        """获取单个交易对行情."""

        resp = self._market.get_ticker(instId=inst_id)
        return self._ensure_success(resp)

    def get_tickers(self, inst_type: str = "SWAP") -> Dict[str, Any]:
        """批量获取某类合约的 tickers."""

        resp = self._market.get_tickers(instType=inst_type)
        return self._ensure_success(resp)

    def get_order_book(self, inst_id: str, depth: int = 5) -> Dict[str, Any]:
        """获取盘口深度."""

        resp = self._market.get_books(instId=inst_id, sz=str(depth))
        return self._ensure_success(resp)

    def get_trades(self, inst_id: str, limit: int = 20) -> Dict[str, Any]:
        """获取最近成交列表."""

        resp = self._market.get_trades(instId=inst_id, limit=str(limit) if limit else "")
        return self._ensure_success(resp)

    def get_funding_rate(self, inst_id: str) -> Dict[str, Any]:
        """获取永续合约资金费率."""

        resp = self._public.get_funding_rate(instId=inst_id)
        return self._ensure_success(resp)

    def get_open_interest(self, inst_id: str) -> Dict[str, Any]:
        """获取合约持仓量."""

        resp = self._public.get_open_interest(instId=inst_id)
        return self._ensure_success(resp)

    def get_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        after: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """K线数据."""

        resp = self._market.get_candles(
            instId=inst_id,
            bar=bar,
            after=after or "",
            before=before or "",
            limit=str(limit) if limit else "",
        )
        return self._ensure_success(resp)

    def get_trade_fills(
        self,
        inst_type: str = "SWAP",
        begin: Optional[str] = None,
        end: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """获取近 3 天的成交明细."""

        resp = self._trade.get_fills(
            instType=inst_type or "",
            begin=begin or "",
            end=end or "",
            after=after or "",
            limit=str(limit),
        )
        return self._ensure_success(resp)

    def get_trade_fills_history(
        self,
        inst_type: str = "SWAP",
        begin: Optional[str] = None,
        end: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """获取近 3 个月的成交明细."""

        resp = self._trade.get_fills_history(
            instType=inst_type,
            begin=begin or "",
            end=end or "",
            after=after or "",
            limit=str(limit),
        )
        return self._ensure_success(resp)

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

        payload: Dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
            "px": px or "",
            "clOrdId": cl_ord_id or "",
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
        resp = self._trade.send_request(
            *trade_api._TradeEndpoints.set_order,
            **payload,
        )
        return self._ensure_success(resp)

    def cancel_order(self, inst_id: str, ord_id: Optional[str] = None, cl_ord_id: Optional[str] = None) -> Dict[str, Any]:
        """撤单."""

        resp = self._trade.set_cancel_order(instId=inst_id, ordId=ord_id or "", clOrdId=cl_ord_id or "")
        return self._ensure_success(resp)

    def instruments(self, inst_type: str = "SWAP") -> Dict[str, Any]:
        """查询支持的合约或现货品种."""

        resp = self._public.get_instruments(instType=inst_type)
        return self._ensure_success(resp)

    def get_account_config(self) -> Dict[str, Any]:
        """查看账户配置."""

        resp = self._account.get_config()
        return self._ensure_success(resp)

    def get_positions(self, inst_type: str = "SWAP") -> Dict[str, Any]:
        resp = self._account.get_positions(instType=inst_type)
        return self._ensure_success(resp)

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
