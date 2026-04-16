from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from config.settings import AppSettings, get_settings
from core.analysis import MarketAnalyzer
from core.client import OKXClient
from core.data.performance import PerformanceTracker
from core.data.watchlist_loader import WatchlistManager
from core.engine import ProtectionOrderManager, ProtectionThresholds
from core.engine.position_lifecycle import PositionLifecycleManager
from core.engine.trading import TradingEngine
from core.strategy.core import Strategy
from core.utils import NotificationCenter, build_notification_center


@dataclass
class RuntimeBundle:
    settings: AppSettings
    okx: OKXClient
    engine: TradingEngine
    watchlist_manager: WatchlistManager
    perf_tracker: PerformanceTracker
    notifier: NotificationCenter | None
    protection_monitor: ProtectionOrderManager | None = None
    position_lifecycle_manager: PositionLifecycleManager | None = None

    def close(self) -> None:
        monitor = getattr(self, "protection_monitor", None)
        if monitor is not None:
            try:
                monitor.stop()
            except Exception:
                pass
        lifecycle_manager = getattr(self, "position_lifecycle_manager", None)
        if lifecycle_manager is not None:
            try:
                lifecycle_manager.stop()
            except Exception:
                pass
        try:
            self.okx.close()
        except Exception:
            pass


def configure_logger(log_dir: str) -> None:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    )
    logger.add(
        path / "runtime-cli-{time}.log",
        rotation="1 day",
        retention="7 days",
        enqueue=True,
        level="INFO",
    )


def build_runtime() -> RuntimeBundle:
    settings = get_settings()
    configure_logger(settings.runtime.log_dir)
    okx = OKXClient(settings)
    analyzer = MarketAnalyzer(settings)
    strategy = Strategy(settings=settings)
    engine = TradingEngine(okx, analyzer, strategy, settings, market_stream=None)
    watchlist_manager = WatchlistManager(okx, settings)
    perf_tracker = PerformanceTracker(okx)
    default_tp = max(0.0, float(settings.strategy.default_take_profit_upl_ratio or 0.0))
    default_sl = max(0.0, float(settings.strategy.default_stop_loss_upl_ratio or 0.0))
    protection_monitor = None
    if default_tp > 0 or default_sl > 0:
        protection_monitor = ProtectionOrderManager(
            okx_client=okx,
            thresholds=ProtectionThresholds(
                take_profit_upl_ratio=default_tp,
                stop_loss_upl_ratio=default_sl,
            ),
            default_td_mode=settings.account.okx_td_mode or "cross",
        )
    notifier = build_notification_center(
        enabled=settings.notification.enabled,
        bot_token=settings.notification.telegram_bot_token,
        chat_id=settings.notification.telegram_chat_id,
        api_url=settings.notification.telegram_api_url,
        level=settings.notification.level,
        cooldown_seconds=settings.notification.cooldown_seconds,
    )
    lifecycle_state_path = Path(
        getattr(settings.runtime, "position_lifecycle_state_path", "data/position_lifecycle_state.json")
        or "data/position_lifecycle_state.json"
    )
    position_lifecycle_manager = PositionLifecycleManager(okx_client=okx, state_path=lifecycle_state_path)
    return RuntimeBundle(
        settings=settings,
        okx=okx,
        engine=engine,
        watchlist_manager=watchlist_manager,
        perf_tracker=perf_tracker,
        notifier=notifier,
        protection_monitor=protection_monitor,
        position_lifecycle_manager=position_lifecycle_manager,
    )
