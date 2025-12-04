"""交易引擎：串联行情、策略、下单."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
import time

import pandas as pd

from loguru import logger

from .client import OKXClient
from .data_utils import candles_to_dataframe
from .analysis import LLMService, DecisionLogger, DecisionRecord
from .execution import ExecutionEngine, ExecutionPlan, ExecutionReport
from .data_pipeline import MarketSnapshotCollector
from .models import (
    SignalAction,
    StrategyContext,
    TradeProtection,
    TradeSignal,
)
from .risk import AccountState, RiskAssessment, RiskManager
from config.settings import AppSettings
from .strategy import Strategy, StrategyOutput
from .protection import build_protection_settings
from .market_stream import MarketDataStream

class TradingEngine:
    """单次运行或循环运行的交易引擎."""

    def __init__(
        self,
        okx_client: OKXClient,
        deepseek_service: LLMService,
        strategy: Strategy,
        settings: AppSettings,
        market_stream: Optional[MarketDataStream] = None,
    ) -> None:
        self.okx = okx_client
        self.deepseek = deepseek_service
        self.strategy = strategy
        self.settings = settings
        self.account_settings = settings.account
        self.strategy_settings = settings.strategy
        self.balance_usage_ratio = self.strategy_settings.balance_usage_ratio
        leverage = getattr(self.strategy_settings, "default_leverage", 1.0)
        try:
            leverage_value = float(leverage)
        except (TypeError, ValueError):
            leverage_value = 1.0
        self.leverage = max(1.0, leverage_value)
        self._pos_mode: Optional[str] = None
        self.risk_manager = RiskManager()
        self.execution_engine = ExecutionEngine(okx_client)
        self.decision_logger = DecisionLogger()
        self.market_stream = market_stream
        self.snapshot_collector = MarketSnapshotCollector(okx_client, stream=market_stream)
        self._default_protection_config = self._build_default_protection_config()
        self._candle_cache: Dict[Tuple[str, str, int], Tuple[float, pd.DataFrame]] = {}
        self._candle_cache_lock = Lock()
        self._candle_cache_ttl = 30  # seconds
        self._max_candle_cache = 64

    def run_once(
        self,
        inst_id: str,
        timeframe: str = "5m",
        limit: int = 200,
        dry_run: bool = True,
        max_position: float = 0.001,
        higher_timeframes: Optional[Tuple[str, ...]] = ("15m", "1H"),
        account_snapshot: Optional[Dict[str, float]] = None,
        protection_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行一次完整流程."""

        features = self._fetch_features(inst_id, timeframe, limit)
        higher_features = self._fetch_multi_timeframes(
            inst_id=inst_id,
            base_timeframe=timeframe,
            timeframes=higher_timeframes,
            limit=limit,
        )
        snapshot = self.snapshot_collector.build(inst_id)
        account_snapshot = account_snapshot or self._fetch_account_snapshot()
        analysis_result = self.deepseek.analyze(
            inst_id,
            timeframe,
            features,
            higher_features,
            snapshot=snapshot,
        )
        analysis = analysis_result.text
        account_state = self._to_account_state(account_snapshot)
        protection_config = self._merge_protection_config(protection_overrides)
        context = StrategyContext(
            inst_id=inst_id,
            timeframe=timeframe,
            dry_run=dry_run,
            max_position=max_position,
            leverage=self.leverage,
            risk_note=self._build_risk_note(account_snapshot),
            higher_timeframes=tuple(higher_timeframes or ()),
            account_equity=account_snapshot.get("equity"),
            available_balance=account_snapshot.get("available"),
            protection=build_protection_settings(protection_config),
        )
        strategy_output = self.strategy.generate_signal(context, features, analysis, higher_features)
        risk_assessment = self.risk_manager.evaluate(account_state, features, higher_features, strategy_output)
        signal = self._cap_signal_by_balance(risk_assessment.trade_signal, features, account_snapshot, inst_id)
        latest_row = features.iloc[-1]
        td_mode = self._determine_td_mode(inst_id)
        pos_side = self._determine_pos_side(signal.action, inst_id) if signal.action != SignalAction.HOLD else None
        execution_plan = self.execution_engine.build_plan(
            inst_id=inst_id,
            signal=signal,
            td_mode=td_mode,
            pos_side=pos_side,
            latest_price=float(latest_row.get("close", 0.0) or 0.0),
            atr=float(latest_row.get("atr", 0.0) or 0.0),
        )
        execution_report: Optional[ExecutionReport] = None
        order_result = None
        if not dry_run and not execution_plan.blocked:
            execution_report = self.execution_engine.execute(execution_plan)
            if execution_report.success and execution_report.response and not execution_report.response.get("error"):
                order_result = execution_report.response
            else:
                order_result = execution_report.response or {
                    "error": {
                        "code": execution_report.code if execution_report else "",
                        "message": execution_report.error if execution_report else "执行失败",
                    }
                }
        elif execution_plan.blocked:
            logger.debug(
                "执行计划被阻止 inst={inst} reason={reason}",
                inst=inst_id,
                reason=execution_plan.block_reason,
            )
        logger.debug(
            "运行完成 inst={inst} action={action} conf={conf:.2f} dry_run={dry_run}",
            inst=inst_id,
            action=signal.action,
            conf=signal.confidence,
            dry_run=dry_run,
        )
        self._log_decision(
            features=features,
            inst_id=inst_id,
            timeframe=timeframe,
            summary=analysis_result.summary,
            strategy_output=strategy_output,
            signal=signal,
        )
        return {
            "analysis": analysis,
            "analysis_summary": analysis_result.summary,
            "history_hint": analysis_result.history_hint,
            "signal": signal,
            "execution": {
                "plan": execution_plan,
                "report": execution_report,
            },
            "order": order_result,
        }

    def _fetch_features(self, inst_id: str, timeframe: str, limit: int):
        if self.market_stream:
            streamed = self.market_stream.get_candle_data(inst_id, timeframe, limit)
            if streamed:
                df = candles_to_dataframe(streamed)
                if len(df) >= min(limit // 2, 20):
                    return df
        key = (inst_id, timeframe, limit)
        now = time.time()
        with self._candle_cache_lock:
            cached = self._candle_cache.get(key)
            if cached and now - cached[0] < self._candle_cache_ttl:
                return cached[1].copy(deep=True)
        resp = self.okx.get_candles(inst_id=inst_id, bar=timeframe, limit=limit)
        df = candles_to_dataframe(resp["data"])
        with self._candle_cache_lock:
            self._candle_cache[key] = (now, df)
            if len(self._candle_cache) > self._max_candle_cache:
                oldest_key = next(iter(self._candle_cache))
                self._candle_cache.pop(oldest_key, None)
        return df.copy(deep=True)

    def _fetch_multi_timeframes(
        self,
        inst_id: str,
        base_timeframe: str,
        timeframes: Optional[Tuple[str, ...]],
        limit: int,
    ) -> Dict[str, Any]:
        if not timeframes:
            return {}
        data: Dict[str, Any] = {}
        base_key = base_timeframe.lower()
        valid_timeframes: list[str] = []
        for tf in timeframes:
            if not tf:
                continue
            tf_key = tf.strip()
            if not tf_key or tf_key.lower() == base_key:
                continue
            valid_timeframes.append(tf_key)
        if not valid_timeframes:
            return data
        # 单周期直接串行，多个周期时启用线程池并发抓取，降低等待时间
        if len(valid_timeframes) == 1:
            tf_key = valid_timeframes[0]
            try:
                data[tf_key] = self._fetch_features(inst_id, tf_key, limit // 2 or 50)
            except Exception as exc:  # pragma: no cover
                logger.warning(f"获取 {inst_id} {tf_key} K线失败: {exc}")
            return data
        max_workers = min(4, len(valid_timeframes))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._fetch_features, inst_id, tf_key, limit // 2 or 50): tf_key
                for tf_key in valid_timeframes
            }
            for future in as_completed(futures):
                tf_key = futures[future]
                try:
                    data[tf_key] = future.result()
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"获取 {inst_id} {tf_key} K线失败: {exc}")
        return data

    def _cap_signal_by_balance(
        self,
        signal: TradeSignal,
        features: Any,
        account_snapshot: Dict[str, float],
        inst_id: str,
    ) -> TradeSignal:
        if signal.size <= 0:
            return signal
        available = float(account_snapshot.get("available") or 0.0)
        if available <= 0:
            return signal
        latest = getattr(features, "iloc", None)
        if latest is None:
            return signal
        try:
            close = float(features.iloc[-1].get("close", 0.0))
        except Exception:
            close = 0.0
        if close <= 0:
            return signal
        max_notional = available * self.balance_usage_ratio * self.leverage
        max_size = max_notional / close
        min_trade_size = None
        if getattr(self, "execution_engine", None):
            try:
                min_trade_size = self.execution_engine.get_min_underlying_size(inst_id, close)
            except Exception as exc:  # pragma: no cover
                logger.debug("获取最小下单失败 inst={inst} err={err}", inst=inst_id, err=exc)
        if max_size <= 0:
            logger.warning(
                "资金限制：inst={inst} 可用资金 {available:.6f} 不足以支持任何仓位，跳过下单。",
                inst=inst_id,
                available=available,
            )
            return TradeSignal(
                action=signal.action,
                confidence=signal.confidence,
                reason=f"{signal.reason}\n\n资金限制：账户可用资金不足，跳过此次下单。",
                size=0.0,
                protection=None,
            )
        notes: list[str] = []
        adjusted_size = signal.size
        if min_trade_size and min_trade_size > 0:
            if min_trade_size - max_size > 1e-12:
                note = (
                    f"资金限制：账户可用 {available:.4f} USD，仅使用 {self.balance_usage_ratio*100:.0f}% ，"
                    f"杠杆 {self.leverage:.2f}x 亦无法满足最小下单 {min_trade_size:.6f}。"
                )
                return TradeSignal(
                    action=signal.action,
                    confidence=signal.confidence,
                    reason=f"{signal.reason}\n\n{note}",
                    size=0.0,
                    protection=None,
                )
            if adjusted_size < min_trade_size:
                notes.append(f"最小下单量 {min_trade_size:.6f}，已自动抬升仓位。")
                adjusted_size = min_trade_size
        if adjusted_size <= max_size + 1e-12:
            if not notes and abs(adjusted_size - signal.size) <= 1e-12:
                return signal
            reason_text = signal.reason
            if notes:
                prefix = " ".join(notes)
                reason_text = f"{reason_text}\n\n{prefix}"
            return TradeSignal(
                action=signal.action,
                confidence=signal.confidence,
                reason=reason_text,
                size=adjusted_size,
                protection=signal.protection,
            )
        capped_size = max(0.0, max_size)
        note = (
            f"资金限制：可用资金 {available:.4f} USD，仅使用 {self.balance_usage_ratio*100:.0f}% ，"
            f"杠杆 {self.leverage:.2f}x 下单数量由 {adjusted_size:.6f} 调整为 {capped_size:.6f}。"
        )
        if notes:
            prefix = " ".join(notes)
            note = f"{prefix} {note}".strip()
        logger.debug(
            "资金限制 inst={inst} size {before:.6f}->{after:.6f} available={avail:.4f} close={close:.6f}",
            inst=inst_id,
            before=adjusted_size,
            after=capped_size,
            avail=available,
            close=close,
        )
        return TradeSignal(
            action=signal.action,
            confidence=signal.confidence,
            reason=f"{signal.reason}\n\n{note}",
            size=capped_size,
            protection=signal.protection,
        )

    def _build_default_protection_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        tp_pct = self._sanitize_positive_value(getattr(self.strategy_settings, "default_take_profit_pct", 0.0))
        if tp_pct > 0:
            config["take_profit"] = {
                "mode": "percent",
                "value": tp_pct,
                "trigger_type": "last",
                "order_type": "market",
            }
        sl_pct = self._sanitize_positive_value(getattr(self.strategy_settings, "default_stop_loss_pct", 0.0))
        if sl_pct > 0:
            config["stop_loss"] = {
                "mode": "percent",
                "value": sl_pct,
                "trigger_type": "last",
                "order_type": "market",
            }
        return config

    def _merge_protection_config(self, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        base = self._default_protection_config or {}
        overrides = overrides if isinstance(overrides, dict) else {}
        for key in ("take_profit", "stop_loss"):
            base_rule = base.get(key)
            if base_rule:
                merged[key] = dict(base_rule)
            override_rule = overrides.get(key)
            if isinstance(override_rule, dict):
                combined = dict(merged.get(key, {}))
                for field, value in override_rule.items():
                    combined[field] = value
                merged[key] = combined
        if not merged and overrides:
            for key, value in overrides.items():
                if isinstance(value, dict):
                    merged[key] = dict(value)
        return merged

    @staticmethod
    def _sanitize_positive_value(value: Any) -> float:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    def _fetch_account_snapshot(self) -> Dict[str, float]:
        resp: Optional[Dict[str, Any]] = None
        snapshot: Dict[str, float] = {}
        try:
            resp = self.okx.get_account_balance()
            snapshot = self.build_account_snapshot(resp)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"获取账户快照失败: {exc}")
        return snapshot

    def build_account_snapshot(self, balance_resp: Optional[Dict[str, Any]]) -> Dict[str, float]:
        """根据账户余额响应构建快照，便于复用."""

        if not balance_resp:
            return {}
        data = balance_resp.get("data") or []
        if not data:
            return {}
        entry = data[0]
        equity = float(entry.get("totalEq", 0) or 0)
        avail = 0.0
        details = entry.get("details") or []
        if details:
            try:
                avail = sum(float(item.get("availBal", 0) or 0) for item in details)
            except (TypeError, ValueError):
                avail = float(entry.get("cashBal", 0) or 0)
        else:
            avail = float(entry.get("cashBal", 0) or 0)
        return {
            "equity": max(0.0, equity),
            "available": max(0.0, avail),
        }

    @staticmethod
    def _build_risk_note(snapshot: Dict[str, float]) -> Optional[str]:
        equity = snapshot.get("equity")
        available = snapshot.get("available")
        if not equity or not available:
            return None
        ratio = available / equity if equity else 0
        if ratio < 0.25:
            return "账户可用资金低于 25%，建议缩小仓位或减仓。"
        if ratio > 0.7:
            return "账户可用资金充足，可适度提高仓位，但务必设置风控。"
        return None

    def _log_decision(
        self,
        features: Any,
        inst_id: str,
        timeframe: str,
        summary: str,
        strategy_output: StrategyOutput,
        signal: TradeSignal,
    ) -> None:
        try:
            ts_value = features.iloc[-1].get("ts", "")
            timestamp = str(ts_value)
            close_price = float(features.iloc[-1].get("close", 0.0) or 0.0)
            llm_view = strategy_output.llm_view
            record = DecisionRecord(
                timestamp=timestamp,
                inst_id=inst_id,
                timeframe=timeframe,
                summary=summary,
                llm_action=llm_view.action.value,
                llm_confidence=llm_view.confidence,
                llm_reason=llm_view.reason,
                strategy_action=signal.action.value,
                close_price=close_price,
            )
            self.decision_logger.log(record)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"记录 LLM 决策失败: {exc}")

    @staticmethod
    def _to_account_state(snapshot: Dict[str, float]) -> AccountState:
        equity = float(snapshot.get("equity") or 0.0)
        available = float(snapshot.get("available") or 0.0)
        pnl = float(snapshot.get("pnl", 0.0) or 0.0)
        under_risk_control = bool(snapshot.get("under_risk_control", False))
        extra = {k: v for k, v in snapshot.items() if k not in {"equity", "available", "pnl", "under_risk_control"}}
        return AccountState(
            equity=equity,
            available=available,
            pnl=pnl,
            under_risk_control=under_risk_control,
            extra=extra or None,
        )

    def _determine_td_mode(self, inst_id: str) -> str:
        if self.account_settings.okx_td_mode:
            return self.account_settings.okx_td_mode
        inst = inst_id.upper()
        if inst.endswith("-SWAP") or inst.endswith("-FUTURES"):
            return "cross"
        return "cash"

    def _determine_pos_side(self, action: SignalAction, inst_id: str) -> Optional[str]:
        if not self._need_pos_side(inst_id):
            return None
        return "long" if action == SignalAction.BUY else "short"

    def _need_pos_side(self, inst_id: str) -> bool:
        inst = inst_id.upper()
        if not (inst.endswith("-SWAP") or inst.endswith("-FUTURES")):
            return False
        if self.account_settings.okx_force_pos_side is not None:
            return self.account_settings.okx_force_pos_side
        mode = self._get_account_pos_mode()
        if not mode:
            return True
        return mode.lower() == "long_short_mode"

    def _get_account_pos_mode(self) -> Optional[str]:
        if self._pos_mode is not None:
            return self._pos_mode
        try:
            config = self.okx.get_account_config()
            data = config.get("data") or []
            if data:
                self._pos_mode = data[0].get("posMode")
        except Exception as exc:  # pragma: no cover
            logger.warning(f"查询账户配置失败: {exc}")
            self._pos_mode = None
        return self._pos_mode
