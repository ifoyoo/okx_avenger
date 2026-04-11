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
from core.engine.trading import TradingEngine
from core.strategy.core import Strategy


@dataclass
class RuntimeBundle:
    settings: AppSettings
    okx: OKXClient
    engine: TradingEngine
    watchlist_manager: WatchlistManager
    perf_tracker: PerformanceTracker

    def close(self) -> None:
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
    return RuntimeBundle(
        settings=settings,
        okx=okx,
        engine=engine,
        watchlist_manager=watchlist_manager,
        perf_tracker=perf_tracker,
    )
