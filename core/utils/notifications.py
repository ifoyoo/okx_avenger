"""Notification helpers (Telegram bot)."""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

import requests
from loguru import logger


class Notifier:
    """Base notifier interface."""

    def send(self, message: str, parse_mode: Optional[str] = None) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def should_send(self, event_key: Tuple[str, str]) -> bool:
        return True


class TelegramNotifier(Notifier):
    """Send notifications to Telegram bot/chat."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        api_url: str = "https://api.telegram.org",
        timeout: float = 5.0,
        cooldown_seconds: float = 600.0,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cooldown_seconds = cooldown_seconds
        self._last_notified: Dict[Tuple[str, str], float] = {}

    def should_send(self, event_key: Tuple[str, str]) -> bool:
        now = time.time()
        with self._lock:
            last_ts = self._last_notified.get(event_key)
            if last_ts and now - last_ts < self._cooldown_seconds:
                return False
            self._last_notified[event_key] = now
            return True

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


def build_notifier(
    enabled: bool,
    bot_token: Optional[str],
    chat_id: Optional[str],
    api_url: str,
    cooldown_seconds: float = 600.0,
) -> Optional[Notifier]:
    if not enabled:
        return None
    if not bot_token or not chat_id:
        logger.warning("通知已启用但缺少 Telegram 配置，忽略推送。")
        return None
    return TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        api_url=api_url,
        cooldown_seconds=cooldown_seconds,
    )
