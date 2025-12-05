"""OKX WebSocket 行情流缓存."""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from threading import Event, Lock, Thread
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from loguru import logger

try:
    import websocket  # type: ignore
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore


class MarketDataStream:
    """连接 OKX 公共 WebSocket，缓存 K 线 / 盘口 / 成交."""

    PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

    def __init__(self, max_candles: int = 600) -> None:
        if websocket is None:
            raise RuntimeError("缺少 websocket-client 依赖，请先安装。")
        self._max_candles = max_candles
        self._candles: Dict[Tuple[str, str], Deque[List[str]]] = defaultdict(
            lambda: deque(maxlen=self._max_candles)
        )
        self._order_books: Dict[str, Tuple[dict, float]] = {}
        self._trades: Dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=200))
        self._subscriptions: set[Tuple[str, str]] = set()
        self._pending_args: List[Dict[str, str]] = []
        self._lock = Lock()
        self._send_lock = Lock()
        self._ws_app: Optional[websocket.WebSocketApp] = None
        self._ws_ready = Event()
        self._stop = Event()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    # --- Public API -----------------------------------------------------

    def close(self) -> None:
        self._stop.set()
        self._ws_ready.clear()
        if self._ws_app:
            try:
                self._ws_app.close()
            except Exception:
                pass
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def ensure_subscriptions(
        self,
        inst_id: str,
        base_timeframe: str,
        higher_timeframes: Iterable[str],
    ) -> None:
        """订阅某个品种的基础周期、上级周期与盘口/成交."""

        self._subscribe_channel(f"candle{base_timeframe}", inst_id)
        for tf in higher_timeframes:
            if tf:
                self._subscribe_channel(f"candle{tf}", inst_id)
        self._subscribe_channel("books5", inst_id)
        self._subscribe_channel("trades", inst_id)

    def get_candle_data(self, inst_id: str, timeframe: str, limit: int) -> Optional[List[List[str]]]:
        key = (inst_id, timeframe)
        with self._lock:
            data = self._candles.get(key)
            if not data:
                return None
            slice_data = list(data)[-limit:]
        if not slice_data:
            return None
        # WebSocket 下发按时间升序，转换为 REST 风格（最新在前）
        slice_data = list(reversed(slice_data))
        return [list(entry) for entry in slice_data]

    def get_order_book_stats(self, inst_id: str, stale_seconds: float = 5) -> Optional[dict]:
        now = time.time()
        with self._lock:
            entry = self._order_books.get(inst_id)
        if not entry:
            return None
        snapshot, ts = entry
        if now - ts > stale_seconds:
            return None
        return snapshot

    def get_trade_stats(self, inst_id: str, stale_seconds: float = 5) -> Optional[List[dict]]:
        now = time.time()
        with self._lock:
            trades = list(self._trades.get(inst_id) or [])
        if not trades:
            return None
        latest_ts = trades[-1].get("ts")
        if latest_ts and now - (int(latest_ts) / 1000) > stale_seconds:
            return None
        return trades

    # --- Internal: WebSocket management ---------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._ws_app = websocket.WebSocketApp(
                    self.PUBLIC_WS_URL,
                    on_open=self._on_open,
                    on_close=self._on_close,
                    on_error=self._on_error,
                    on_message=self._on_message,
                )
                self._ws_app.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(f"WebSocket 连接异常: {exc}")
            self._ws_ready.clear()
            if self._stop.is_set():
                break
            time.sleep(3)

    def _send(self, payload: dict) -> None:
        message = json.dumps(payload)
        with self._send_lock:
            if self._ws_app:
                try:
                    self._ws_app.send(message)
                except Exception:
                    logger.debug("WebSocket 发送失败，加入待发送队列。")
                    self._pending_args.append(payload["args"][0])

    def _subscribe_channel(self, channel: str, inst_id: str) -> None:
        key = (channel, inst_id)
        with self._lock:
            if key in self._subscriptions:
                return
            self._subscriptions.add(key)
        arg = {"channel": channel, "instId": inst_id}
        if self._ws_ready.is_set():
            self._send({"op": "subscribe", "args": [arg]})
        else:
            with self._lock:
                self._pending_args.append(arg)

    def _flush_pending(self) -> None:
        with self._lock:
            pending = list(self._pending_args)
            self._pending_args.clear()
        if not pending:
            return
        batch = {"op": "subscribe", "args": pending}
        self._send(batch)

    # --- WebSocket callbacks --------------------------------------------

    def _on_open(self, _ws) -> None:  # pragma: no cover - 网络相关
        logger.info("WebSocket 已连接 OKX 公共频道。")
        self._ws_ready.set()
        self._flush_pending()

    def _on_close(self, _ws, *_args) -> None:  # pragma: no cover - 网络相关
        logger.warning("WebSocket 连接已关闭。")
        self._ws_ready.clear()

    def _on_error(self, _ws, error) -> None:  # pragma: no cover - 网络相关
        logger.warning(f"WebSocket 错误: {error}")

    def _on_message(self, _ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if "arg" not in payload or "data" not in payload:
            return
        arg = payload["arg"]
        channel = arg.get("channel")
        inst_id = arg.get("instId")
        if not channel or not inst_id:
            return
        data = payload["data"]
        if channel.startswith("candle"):
            timeframe = channel.replace("candle", "")
            self._handle_candle(inst_id, timeframe, data)
        elif channel == "books5":
            self._handle_order_book(inst_id, data)
        elif channel == "trades":
            self._handle_trades(inst_id, data)

    # --- Handlers -------------------------------------------------------

    def _handle_candle(self, inst_id: str, timeframe: str, data: List[List[str]]) -> None:
        key = (inst_id, timeframe)
        with self._lock:
            buffer = self._candles[key]
            for entry in data:
                ts = entry[0]
                # 如果最后一条时间戳相同，则替换
                if buffer and buffer[-1][0] == ts:
                    buffer[-1] = entry
                else:
                    buffer.append(entry)

    def _handle_order_book(self, inst_id: str, data: List[dict]) -> None:
        if not data:
            return
        snapshot = data[0]
        bids = snapshot.get("bids") or []
        asks = snapshot.get("asks") or []
        if not bids or not asks:
            return
        try:
            top_bid = float(bids[0][0])
            top_ask = float(asks[0][0])
            spread = (top_ask - top_bid) / top_bid if top_bid else 0.0
            bid_volume = sum(float(item[1]) for item in bids[:5])
            ask_volume = sum(float(item[1]) for item in asks[:5])
            total = bid_volume + ask_volume
            imbalance = (bid_volume - ask_volume) / total if total else 0.0
        except Exception:
            return
        stats = {
            "spread_pct": spread,
            "imbalance": imbalance,
            "top_bid": top_bid,
            "top_ask": top_ask,
        }
        with self._lock:
            self._order_books[inst_id] = (stats, time.time())

    def _handle_trades(self, inst_id: str, data: List[dict]) -> None:
        if not data:
            return
        with self._lock:
            buffer = self._trades[inst_id]
            for trade in data:
                buffer.append(trade)
