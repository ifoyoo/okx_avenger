"""Runtime-focused notification helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple

import requests
from loguru import logger


class Notifier(Protocol):
    def send(self, message: str, parse_mode: Optional[str] = None) -> None:
        """Send a rendered message through one transport."""


class TelegramNotifier:
    """Telegram transport for rendered notification messages."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        api_url: str = "https://api.telegram.org",
        timeout: float = 5.0,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._lock = threading.Lock()

    def send(self, message: str, parse_mode: Optional[str] = None) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        url = f"{self.api_url}/bot{self.bot_token}/sendMessage"
        with self._lock:
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code >= 400:
                    logger.warning("Telegram 通知失败 code={} body={}", resp.status_code, resp.text)
            except Exception as exc:  # pragma: no cover - 网络异常
                logger.warning(f"发送 Telegram 通知失败: {exc}")


@dataclass(frozen=True)
class NotificationEvent:
    kind: str
    message: str
    inst_id: str = ""
    timeframe: str = ""
    parse_mode: Optional[str] = None

    def cooldown_key(self) -> Tuple[str, str]:
        scope = self.inst_id or self.timeframe or "global"
        if self.inst_id and self.timeframe:
            scope = f"{self.inst_id}@{self.timeframe}"
        return self.kind, scope


class NotificationCenter:
    """Filter runtime events by level and cooldown before dispatching."""

    def __init__(
        self,
        transport: Optional[Notifier],
        level: str = "critical",
        cooldown_seconds: float = 600.0,
    ) -> None:
        self.transport = transport
        self.level = self.normalize_level(level)
        self.cooldown_seconds = max(0.0, float(cooldown_seconds or 0.0))
        self._lock = threading.Lock()
        self._last_sent: Dict[Tuple[str, str], float] = {}

    @staticmethod
    def normalize_level(level: object) -> str:
        normalized = str(level or "critical").strip().lower()
        if normalized not in {"critical", "orders", "all"}:
            return "critical"
        return normalized

    def publish(self, event: NotificationEvent) -> bool:
        if self.transport is None:
            return False
        if not self._level_allows(event.kind):
            return False
        if not self._consume_cooldown(event.cooldown_key()):
            return False
        self.transport.send(event.message, parse_mode=event.parse_mode)
        return True

    def _level_allows(self, kind: str) -> bool:
        critical = {"runtime_error", "trade_blocked", "order_failed"}
        if self.level == "critical":
            return kind in critical
        if self.level in {"orders", "all"}:
            return kind in critical | {"order_submitted"}
        return False

    def _consume_cooldown(self, key: Tuple[str, str]) -> bool:
        if self.cooldown_seconds <= 0:
            return True
        now = time.time()
        with self._lock:
            last_ts = self._last_sent.get(key)
            if last_ts and now - last_ts < self.cooldown_seconds:
                return False
            self._last_sent[key] = now
            return True


def build_notification_center(
    enabled: bool,
    bot_token: Optional[str],
    chat_id: Optional[str],
    api_url: str,
    level: str = "critical",
    cooldown_seconds: float = 600.0,
) -> Optional[NotificationCenter]:
    if not enabled:
        return None
    if not bot_token or not chat_id:
        logger.warning("通知已启用但缺少 Telegram 配置，忽略推送。")
        return None
    transport = TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        api_url=api_url,
    )
    return NotificationCenter(
        transport=transport,
        level=level,
        cooldown_seconds=cooldown_seconds,
    )


def build_notifier(
    enabled: bool,
    bot_token: Optional[str],
    chat_id: Optional[str],
    api_url: str,
    cooldown_seconds: float = 600.0,
) -> Optional[NotificationCenter]:
    """Backward-compatible alias for legacy imports."""

    return build_notification_center(
        enabled=enabled,
        bot_token=bot_token,
        chat_id=chat_id,
        api_url=api_url,
        cooldown_seconds=cooldown_seconds,
    )
