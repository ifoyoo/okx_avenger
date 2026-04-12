"""交易引擎：串联行情、策略、下单."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple
import time
import uuid

import pandas as pd

from loguru import logger

from core.client import MarketDataStream, OKXClient
from core.data.features import candles_to_dataframe
from core.analysis import MarketAnalyzer, DecisionLogger, DecisionRecord, MarketAnalysis
from core.analysis.intel import MarketIntelSnapshot, build_news_intel_collector
from core.analysis.llm_brain import BrainDecision, build_llm_brain
from core.engine.execution import ExecutionEngine, ExecutionPlan, ExecutionReport
from core.data.snapshot import MarketSnapshotCollector
from core.models import (
    SignalAction,
    StrategyContext,
    TradeSignal,
)
from core.engine.risk import AccountState, RiskAssessment, RiskManager
from config.settings import AppSettings
from core.strategy.core import Strategy, StrategyOutput
from core.protection import build_protection_settings


@dataclass
class DataBundle:
    features: pd.DataFrame
    higher_features: Dict[str, Any]
    snapshot: Any
    account_snapshot: Dict[str, float]
    risk_note: Optional[str]


@dataclass
class AnalysisBundle:
    analysis_result: MarketAnalysis
    analysis_text: str
    strategy_analysis_text: str
    brain_decision: Optional[BrainDecision]
    market_intel: Optional[MarketIntelSnapshot]


@dataclass
class StrategyBundle:
    context: StrategyContext
    strategy_output: StrategyOutput


@dataclass
class RiskBundle:
    account_state: AccountState
    risk_assessment: RiskAssessment
    signal: TradeSignal


@dataclass
class ExecutionBundle:
    plan: ExecutionPlan
    report: Optional[ExecutionReport]
    order: Optional[Dict[str, Any]]


class TradingEngine:
    """单次运行或循环运行的交易引擎."""

    def __init__(
        self,
        okx_client: OKXClient,
        analyzer: MarketAnalyzer,
        strategy: Strategy,
        settings: AppSettings,
        market_stream: Optional[MarketDataStream] = None,
    ) -> None:
        self.okx = okx_client
        self.analyzer = analyzer
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
        daily_loss_limit = self._sanitize_positive_value(
            getattr(self.strategy_settings, "risk_daily_loss_limit", 0.0)
        )
        daily_loss_limit_pct = self._sanitize_positive_value(
            getattr(self.strategy_settings, "risk_daily_loss_limit_pct", 0.0)
        )
        try:
            consecutive_loss_limit = max(
                0, int(getattr(self.strategy_settings, "risk_consecutive_loss_limit", 0) or 0)
            )
        except (TypeError, ValueError):
            consecutive_loss_limit = 0
        try:
            consecutive_cooldown_minutes = max(
                1,
                int(getattr(self.strategy_settings, "risk_consecutive_cooldown_minutes", 180) or 180),
            )
        except (TypeError, ValueError):
            consecutive_cooldown_minutes = 180
        risk_state_path = str(
            getattr(self.strategy_settings, "risk_state_path", "data/risk_circuit_state.json")
            or "data/risk_circuit_state.json"
        )
        runtime_settings = getattr(settings, "runtime", None)
        try:
            data_staleness_seconds = int(getattr(runtime_settings, "data_staleness_seconds", 180) or 180)
        except (TypeError, ValueError):
            data_staleness_seconds = 180
        try:
            feature_min_samples = int(getattr(runtime_settings, "feature_min_samples", 80) or 80)
        except (TypeError, ValueError):
            feature_min_samples = 80
        feature_indicator_overrides = str(getattr(runtime_settings, "feature_indicator_overrides", "") or "")
        try:
            execution_pending_timeout_seconds = float(
                getattr(runtime_settings, "execution_pending_timeout_seconds", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            execution_pending_timeout_seconds = 0.0
        execution_reconcile_position = bool(
            getattr(runtime_settings, "execution_reconcile_position", True)
        )
        intel_settings = settings.intel
        self.data_staleness_seconds = max(0, data_staleness_seconds)
        self.feature_min_samples = max(1, feature_min_samples)
        self.feature_indicator_overrides = feature_indicator_overrides
        self._pos_mode: Optional[str] = None
        self.risk_manager = RiskManager(
            daily_loss_limit=daily_loss_limit,
            daily_loss_limit_pct=daily_loss_limit_pct,
            consecutive_loss_limit=consecutive_loss_limit,
            consecutive_cooldown_minutes=consecutive_cooldown_minutes,
            state_path=risk_state_path,
            intel_gate_mode=intel_settings.event_gate_mode,
            intel_degrade_threshold=float(intel_settings.event_gate_degrade_threshold),
            intel_block_threshold=float(intel_settings.event_gate_block_threshold),
            intel_degrade_confidence_cap=float(intel_settings.event_gate_degrade_confidence_cap),
            intel_degrade_size_ratio=float(intel_settings.event_gate_degrade_size_ratio),
        )
        self.execution_engine = ExecutionEngine(
            okx_client,
            pending_timeout_seconds=max(0.0, execution_pending_timeout_seconds),
            reconcile_position=execution_reconcile_position,
        )
        self.decision_logger = DecisionLogger()
        self.market_stream = market_stream
        self.snapshot_collector = MarketSnapshotCollector(okx_client, stream=market_stream)
        self.llm_brain = build_llm_brain(settings)
        self.news_intel_collector = build_news_intel_collector(settings)
        self._default_protection_config = self._build_default_protection_config()
        self._candle_cache: Dict[Tuple[str, str, int], Tuple[float, pd.DataFrame]] = {}
        self._candle_cache_lock = Lock()
        self._candle_cache_ttl = 30  # seconds
        self._max_candle_cache = 64
        self._higher_tf_cache_ttl = 180.0  # seconds
        self._pipeline_runs = 0
        self._pipeline_failures = 0

    def run_once(
        self,
        inst_id: str,
        timeframe: str = "5m",
        limit: int = 200,
        dry_run: bool = True,
        max_position: float = 0.001,
        higher_timeframes: Optional[Tuple[str, ...]] = ("1H",),
        market_intel_query: Optional[str] = None,
        market_intel_coin_id: Optional[str] = None,
        market_intel_aliases: Optional[Sequence[str]] = None,
        account_snapshot: Optional[Dict[str, float]] = None,
        protection_overrides: Optional[Dict[str, Any]] = None,
        positions_snapshot: Optional[List[Dict[str, Any]]] = None,
        perf_stats: Optional[Dict[str, Any]] = None,
        daily_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行一次完整流程."""

        trace_id = self._new_trace_id()
        run_logger = logger.bind(trace_id=trace_id, inst_id=inst_id, timeframe=timeframe)
        self._pipeline_runs += 1
        run_started_at = time.perf_counter()
        run_logger.info(
            "event=run_once_start action={action} blocked={blocked} error_code={error_code} dry_run={dry_run} limit={limit}",
            action="init",
            blocked=False,
            error_code="",
            dry_run=dry_run,
            limit=limit,
        )
        try:
            step_started = time.perf_counter()
            data_bundle = self._run_data_step(
                inst_id=inst_id,
                timeframe=timeframe,
                limit=limit,
                higher_timeframes=higher_timeframes,
                account_snapshot=account_snapshot,
            )
            data_ms = (time.perf_counter() - step_started) * 1000.0
            run_logger.info(
                "event=data_done action={action} blocked={blocked} error_code={error_code} rows={rows} higher_tfs={higher_tfs} step_ms={step_ms:.2f}",
                action="data",
                blocked=False,
                error_code="",
                rows=len(data_bundle.features),
                higher_tfs=len(data_bundle.higher_features),
                step_ms=data_ms,
            )
            step_started = time.perf_counter()
            analysis_bundle = self._run_analysis_step(
                inst_id=inst_id,
                timeframe=timeframe,
                data_bundle=data_bundle,
                market_intel_query=market_intel_query,
                market_intel_coin_id=market_intel_coin_id,
                market_intel_aliases=market_intel_aliases,
                positions_snapshot=positions_snapshot,
                perf_stats=perf_stats,
                daily_stats=daily_stats,
            )
            analysis_ms = (time.perf_counter() - step_started) * 1000.0
            run_logger.info(
                "event=analysis_done action={action} blocked={blocked} error_code={error_code} summary_len={summary_len} step_ms={step_ms:.2f}",
                action="analysis",
                blocked=False,
                error_code="",
                summary_len=len(analysis_bundle.analysis_result.summary or ""),
                step_ms=analysis_ms,
            )
            step_started = time.perf_counter()
            strategy_bundle = self._run_strategy_step(
                inst_id=inst_id,
                timeframe=timeframe,
                dry_run=dry_run,
                max_position=max_position,
                higher_timeframes=higher_timeframes,
                protection_overrides=protection_overrides,
                data_bundle=data_bundle,
                analysis_bundle=analysis_bundle,
            )
            strategy_ms = (time.perf_counter() - step_started) * 1000.0
            run_logger.info(
                "event=signal_done action={action} blocked={blocked} error_code={error_code} confidence={confidence:.4f} step_ms={step_ms:.2f}",
                action=strategy_bundle.strategy_output.trade_signal.action.value,
                blocked=False,
                error_code="",
                confidence=strategy_bundle.strategy_output.trade_signal.confidence,
                step_ms=strategy_ms,
            )
            step_started = time.perf_counter()
            risk_bundle = self._run_risk_step(
                inst_id=inst_id,
                data_bundle=data_bundle,
                strategy_output=strategy_bundle.strategy_output,
                market_intel=analysis_bundle.market_intel,
                perf_stats=perf_stats,
                daily_stats=daily_stats,
            )
            risk_ms = (time.perf_counter() - step_started) * 1000.0
            run_logger.info(
                "event=risk_done action={action} blocked={blocked} error_code={error_code} confidence={confidence:.4f} step_ms={step_ms:.2f}",
                action=risk_bundle.signal.action.value,
                blocked=risk_bundle.risk_assessment.blocked,
                error_code="",
                confidence=risk_bundle.signal.confidence,
                step_ms=risk_ms,
            )
            step_started = time.perf_counter()
            execution_bundle = self._run_execution_step(
                inst_id=inst_id,
                timeframe=timeframe,
                trace_id=trace_id,
                dry_run=dry_run,
                signal=risk_bundle.signal,
                features=data_bundle.features,
            )
            execution_ms = (time.perf_counter() - step_started) * 1000.0
        except Exception as exc:
            self._pipeline_failures += 1
            failure_rate = self._pipeline_failures / max(1, self._pipeline_runs)
            run_logger.error(
                "event=run_once_failed action={action} blocked={blocked} error_code={error_code} failure_rate={failure_rate:.2%} err={err}",
                action="error",
                blocked=True,
                error_code="PIPELINE_EXCEPTION",
                failure_rate=failure_rate,
                err=exc,
            )
            raise
        execution_error_code = self._extract_execution_error_code(execution_bundle)
        run_logger.info(
            "event=execution_done action={action} blocked={blocked} error_code={error_code} step_ms={step_ms:.2f}",
            action=risk_bundle.signal.action.value,
            blocked=execution_bundle.plan.blocked,
            error_code=execution_error_code,
            step_ms=execution_ms,
        )
        logger.debug(
            "运行完成 inst={inst} action={action} conf={conf:.2f} dry_run={dry_run}",
            inst=inst_id,
            action=risk_bundle.signal.action,
            conf=risk_bundle.signal.confidence,
            dry_run=dry_run,
        )
        self._log_decision(
            features=data_bundle.features,
            inst_id=inst_id,
            timeframe=timeframe,
            trace_id=trace_id,
            summary=analysis_bundle.analysis_result.summary,
            strategy_output=strategy_bundle.strategy_output,
            signal=risk_bundle.signal,
        )
        total_ms = (time.perf_counter() - run_started_at) * 1000.0
        failure_rate = self._pipeline_failures / max(1, self._pipeline_runs)
        run_logger.info(
            "event=run_once_done action={action} blocked={blocked} error_code={error_code} total_ms={total_ms:.2f} failure_rate={failure_rate:.2%}",
            action=risk_bundle.signal.action.value,
            blocked=execution_bundle.plan.blocked,
            error_code=execution_error_code,
            total_ms=total_ms,
            failure_rate=failure_rate,
        )
        return {
            "trace_id": trace_id,
            "analysis": analysis_bundle.analysis_text,
            "analysis_brain": analysis_bundle.brain_decision.to_dict() if analysis_bundle.brain_decision else None,
            "market_intel": analysis_bundle.market_intel.to_dict() if analysis_bundle.market_intel else None,
            "analysis_summary": analysis_bundle.analysis_result.summary,
            "history_hint": analysis_bundle.analysis_result.history_hint,
            "signal": risk_bundle.signal,
            "execution": {
                "plan": execution_bundle.plan,
                "report": execution_bundle.report,
            },
            "order": execution_bundle.order,
        }

    def _run_data_step(
        self,
        *,
        inst_id: str,
        timeframe: str,
        limit: int,
        higher_timeframes: Optional[Tuple[str, ...]],
        account_snapshot: Optional[Dict[str, float]],
    ) -> DataBundle:
        features = self._fetch_features(inst_id, timeframe, limit)
        higher_features = self._fetch_multi_timeframes(
            inst_id=inst_id,
            base_timeframe=timeframe,
            timeframes=higher_timeframes,
            limit=limit,
        )
        snapshot = self.snapshot_collector.build(inst_id)
        account_data = account_snapshot or self._fetch_account_snapshot()
        risk_note = self._build_risk_note(account_data)
        return DataBundle(
            features=features,
            higher_features=higher_features,
            snapshot=snapshot,
            account_snapshot=account_data,
            risk_note=risk_note,
        )

    def _run_analysis_step(
        self,
        *,
        inst_id: str,
        timeframe: str,
        data_bundle: DataBundle,
        market_intel_query: Optional[str],
        market_intel_coin_id: Optional[str],
        market_intel_aliases: Optional[Sequence[str]],
        positions_snapshot: Optional[List[Dict[str, Any]]],
        perf_stats: Optional[Dict[str, Any]],
        daily_stats: Optional[Dict[str, Any]],
    ) -> AnalysisBundle:
        analysis_result = self.analyzer.analyze(
            inst_id,
            timeframe,
            data_bundle.features,
            data_bundle.higher_features,
            snapshot=data_bundle.snapshot,
            account_snapshot=data_bundle.account_snapshot,
            risk_note=data_bundle.risk_note,
            position_entries=positions_snapshot,
            perf_stats=perf_stats,
            daily_stats=daily_stats,
        )
        analysis_text = analysis_result.text
        strategy_analysis_text = analysis_text
        market_intel = self._collect_market_intel(
            inst_id,
            query_override=market_intel_query,
            coin_id_override=market_intel_coin_id,
            symbol_aliases=market_intel_aliases,
        )
        brain_decision = self._analyze_with_llm_brain(
            inst_id=inst_id,
            timeframe=timeframe,
            features=data_bundle.features,
            higher_features=data_bundle.higher_features,
            analysis_result=analysis_result,
            risk_note=data_bundle.risk_note,
            account_snapshot=data_bundle.account_snapshot,
            market_intel=market_intel,
        )
        if brain_decision:
            strategy_analysis_text = brain_decision.to_analysis_json()
        return AnalysisBundle(
            analysis_result=analysis_result,
            analysis_text=analysis_text,
            strategy_analysis_text=strategy_analysis_text,
            brain_decision=brain_decision,
            market_intel=market_intel,
        )

    def _run_strategy_step(
        self,
        *,
        inst_id: str,
        timeframe: str,
        dry_run: bool,
        max_position: float,
        higher_timeframes: Optional[Tuple[str, ...]],
        protection_overrides: Optional[Dict[str, Any]],
        data_bundle: DataBundle,
        analysis_bundle: AnalysisBundle,
    ) -> StrategyBundle:
        protection_config = self._merge_protection_config(protection_overrides)
        context = StrategyContext(
            inst_id=inst_id,
            timeframe=timeframe,
            dry_run=dry_run,
            max_position=max_position,
            leverage=self.leverage,
            risk_note=data_bundle.risk_note,
            higher_timeframes=tuple(higher_timeframes or ()),
            account_equity=data_bundle.account_snapshot.get("equity"),
            available_balance=data_bundle.account_snapshot.get("available"),
            protection=build_protection_settings(protection_config),
        )
        strategy_output = self.strategy.generate_signal(
            context,
            data_bundle.features,
            analysis_bundle.strategy_analysis_text,
            data_bundle.higher_features,
            llm_influence_enabled=analysis_bundle.brain_decision is not None,
            market_analysis=analysis_bundle.analysis_result,
        )
        return StrategyBundle(
            context=context,
            strategy_output=strategy_output,
        )

    def _run_risk_step(
        self,
        *,
        inst_id: str,
        data_bundle: DataBundle,
        strategy_output: StrategyOutput,
        market_intel: Optional[MarketIntelSnapshot],
        perf_stats: Optional[Dict[str, Any]],
        daily_stats: Optional[Dict[str, Any]],
    ) -> RiskBundle:
        account_state = self._to_account_state(data_bundle.account_snapshot)
        risk_assessment = self.risk_manager.evaluate(
            account_state,
            data_bundle.features,
            data_bundle.higher_features,
            strategy_output,
            daily_stats=daily_stats,
            perf_stats=perf_stats,
            market_intel=market_intel.to_dict() if market_intel else None,
        )
        signal = self._cap_signal_by_balance(
            risk_assessment.trade_signal,
            data_bundle.features,
            data_bundle.account_snapshot,
            inst_id,
        )
        return RiskBundle(
            account_state=account_state,
            risk_assessment=risk_assessment,
            signal=signal,
        )

    def _run_execution_step(
        self,
        *,
        inst_id: str,
        timeframe: str,
        trace_id: str,
        dry_run: bool,
        signal: TradeSignal,
        features: pd.DataFrame,
    ) -> ExecutionBundle:
        exec_logger = logger.bind(trace_id=trace_id, inst_id=inst_id, timeframe=timeframe)
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
            trace_id=trace_id,
        )
        is_stale, stale_reason = self._check_data_freshness(
            features=features,
            timeframe=timeframe,
            inst_id=inst_id,
        )
        if is_stale and stale_reason:
            execution_plan.blocked = True
            execution_plan.block_reason = stale_reason
            execution_plan.protection = None
            execution_plan.notes = tuple(execution_plan.notes) + (stale_reason,)
            exec_logger.warning("event=data_stale_blocked reason={reason}", reason=stale_reason)
        if (
            not execution_plan.blocked
            and signal.action in {SignalAction.BUY, SignalAction.SELL}
            and self.execution_engine.has_live_pending_order(inst_id)
        ):
            pending_reason = f"存在未成交委托：{inst_id} 当前仍有 live pending 单，跳过重复下单。"
            execution_plan.blocked = True
            execution_plan.block_reason = pending_reason
            execution_plan.protection = None
            execution_plan.notes = tuple(execution_plan.notes) + (pending_reason,)
            exec_logger.warning("event=pending_order_blocked reason={reason}", reason=pending_reason)
        execution_report: Optional[ExecutionReport] = None
        order_result: Optional[Dict[str, Any]] = None
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
            exec_logger.debug("event=execution_plan_blocked reason={reason}", reason=execution_plan.block_reason)
        execution_bundle = ExecutionBundle(
            plan=execution_plan,
            report=execution_report,
            order=order_result,
        )
        exec_logger.info(
            "event=execution_result action={action} blocked={blocked} error_code={error_code} success={success} dry_run={dry_run}",
            action=signal.action.value,
            blocked=execution_plan.blocked,
            error_code=self._extract_execution_error_code(execution_bundle),
            success=bool(execution_report.success) if execution_report else False,
            dry_run=dry_run,
        )
        return execution_bundle

    def _check_data_freshness(
        self,
        *,
        features: pd.DataFrame,
        timeframe: str,
        inst_id: str,
    ) -> Tuple[bool, Optional[str]]:
        if self.data_staleness_seconds <= 0:
            return False, None
        age_seconds = self._latest_feature_age_seconds(features)
        if age_seconds is None:
            return False, None
        threshold = max(
            float(self.data_staleness_seconds),
            float(self._timeframe_expected_seconds(timeframe)) * 2.0,
        )
        if age_seconds <= threshold:
            return False, None
        reason = (
            f"数据新鲜度闸门：{inst_id} {timeframe} 最近K线已过期 "
            f"{age_seconds:.0f}s (> {threshold:.0f}s)，跳过下单。"
        )
        return True, reason

    @staticmethod
    def _latest_feature_age_seconds(features: pd.DataFrame) -> Optional[float]:
        if features is None or features.empty:
            return None
        latest = features.iloc[-1]
        ts_value = latest.get("ts")
        ts = TradingEngine._coerce_timestamp(ts_value)
        if ts is None:
            return None
        now = pd.Timestamp.now(tz="UTC")
        delta = (now - ts).total_seconds()
        if delta < 0:
            return 0.0
        return float(delta)

    @staticmethod
    def _coerce_timestamp(value: Any) -> Optional[pd.Timestamp]:
        if value in (None, "", "NaT"):
            return None
        try:
            ts = pd.Timestamp(value)
        except Exception:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            unit = "ms"
            abs_v = abs(numeric)
            if abs_v > 1e17:
                numeric = numeric / 1_000_000
            elif abs_v > 1e13:
                numeric = numeric / 1_000
            ts = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
            if pd.isna(ts):
                return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts

    @staticmethod
    def _timeframe_expected_seconds(timeframe: str) -> int:
        tf = (timeframe or "").strip().lower()
        if not tf:
            return 300
        try:
            if tf.endswith("m"):
                return max(60, int(tf[:-1] or 0) * 60)
            if tf.endswith("h"):
                return max(3600, int(tf[:-1] or 0) * 3600)
            if tf.endswith("d"):
                return max(86400, int(tf[:-1] or 0) * 86400)
            if tf.endswith("w"):
                return max(604800, int(tf[:-1] or 0) * 604800)
        except ValueError:
            return 300
        return 300

    @staticmethod
    def _new_trace_id() -> str:
        return uuid.uuid4().hex[:16]

    @staticmethod
    def _extract_execution_error_code(bundle: ExecutionBundle) -> str:
        if bundle.plan.blocked:
            return "PLAN_BLOCKED"
        if bundle.report:
            if bundle.report.code:
                return str(bundle.report.code)
            response = bundle.report.response if isinstance(bundle.report.response, dict) else {}
            error = response.get("error") if isinstance(response, dict) else None
            if isinstance(error, dict):
                code = error.get("code")
                if code not in (None, ""):
                    return str(code)
        if isinstance(bundle.order, dict):
            error = bundle.order.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                if code not in (None, ""):
                    return str(code)
        return ""

    def _collect_market_intel(
        self,
        inst_id: str,
        *,
        query_override: Optional[str] = None,
        coin_id_override: Optional[str] = None,
        symbol_aliases: Optional[Sequence[str]] = None,
    ) -> Optional[MarketIntelSnapshot]:
        if not self.news_intel_collector:
            return None
        try:
            return self.news_intel_collector.collect(
                inst_id,
                query_override=query_override,
                coin_id_override=coin_id_override,
                symbol_aliases=symbol_aliases,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("新闻情报抓取失败 inst={inst} err={err}", inst=inst_id, err=exc)
            return None

    def _analyze_with_llm_brain(
        self,
        *,
        inst_id: str,
        timeframe: str,
        features: pd.DataFrame,
        higher_features: Dict[str, Any],
        analysis_result: MarketAnalysis,
        risk_note: Optional[str],
        account_snapshot: Dict[str, float],
        market_intel: Optional[MarketIntelSnapshot],
    ) -> Optional[BrainDecision]:
        if not self.llm_brain:
            return None
        try:
            return self.llm_brain.analyze(
                inst_id=inst_id,
                timeframe=timeframe,
                features=features,
                higher_features=higher_features,
                deterministic_summary=analysis_result.summary,
                deterministic_analysis=analysis_result.text,
                risk_note=risk_note,
                account_snapshot=account_snapshot,
                market_intel=market_intel.to_dict() if market_intel else None,
                structured_market_analysis={
                    "trend_direction": analysis_result.trend.direction,
                    "trend_strength": analysis_result.trend.strength,
                    "trend_label": analysis_result.trend.label,
                    "momentum_score": analysis_result.momentum.score,
                    "momentum_label": analysis_result.momentum.label,
                    "supports": list(analysis_result.levels.supports),
                    "resistances": list(analysis_result.levels.resistances),
                    "risk_factors": list(analysis_result.risk.factors),
                },
                structured_market_intel=market_intel.to_dict() if market_intel else None,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("LLM 分析失败 inst={inst} err={err}", inst=inst_id, err=exc)
            return None

    def _fetch_features(
        self,
        inst_id: str,
        timeframe: str,
        limit: int,
        cache_ttl: Optional[float] = None,
    ) -> pd.DataFrame:
        ttl = cache_ttl if cache_ttl is not None else self._timeframe_cache_ttl(timeframe)
        key = (inst_id, timeframe, limit)
        cached = self._get_cached_candles(key, ttl)
        if cached is not None:
            self._ensure_feature_samples(cached, inst_id=inst_id, timeframe=timeframe)
            return cached
        stream_df: Optional[pd.DataFrame] = None
        if self.market_stream:
            streamed = self.market_stream.get_candle_data(inst_id, timeframe, limit)
            if streamed:
                df = candles_to_dataframe(
                    streamed,
                    timeframe=timeframe,
                    inst_id=inst_id,
                    indicator_overrides=self.feature_indicator_overrides,
                ).tail(limit)
                if len(df) >= limit:
                    self._ensure_feature_samples(df, inst_id=inst_id, timeframe=timeframe)
                    self._store_cached_candles(key, df)
                    return df.copy(deep=True)
                stream_df = df
        resp = self.okx.get_candles(inst_id=inst_id, bar=timeframe, limit=limit)
        rest_df = candles_to_dataframe(
            resp["data"],
            timeframe=timeframe,
            inst_id=inst_id,
            indicator_overrides=self.feature_indicator_overrides,
        ).tail(limit)
        if stream_df is not None and not stream_df.empty:
            combined = (
                pd.concat([rest_df, stream_df])
                .drop_duplicates(subset="ts", keep="last")
                .sort_values("ts")
                .tail(limit)
            )
        else:
            combined = rest_df
        self._ensure_feature_samples(combined, inst_id=inst_id, timeframe=timeframe)
        self._store_cached_candles(key, combined)
        return combined.copy(deep=True)

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
                data[tf_key] = self._fetch_features(
                    inst_id,
                    tf_key,
                    limit // 2 or 50,
                    cache_ttl=self._timeframe_cache_ttl(tf_key),
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(f"获取 {inst_id} {tf_key} K线失败: {exc}")
            return data
        max_workers = min(4, len(valid_timeframes))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._fetch_features,
                    inst_id,
                    tf_key,
                    limit // 2 or 50,
                    self._timeframe_cache_ttl(tf_key),
                ): tf_key
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

    def _get_cached_candles(
        self, key: Tuple[str, str, int], ttl: float
    ) -> Optional[pd.DataFrame]:
        now = time.time()
        with self._candle_cache_lock:
            cached = self._candle_cache.get(key)
            if cached and now - cached[0] < ttl:
                return cached[1].copy(deep=True)
        return None

    def _store_cached_candles(self, key: Tuple[str, str, int], df: pd.DataFrame) -> None:
        now = time.time()
        with self._candle_cache_lock:
            self._candle_cache[key] = (now, df)
            if len(self._candle_cache) > self._max_candle_cache:
                oldest_key = next(iter(self._candle_cache))
                self._candle_cache.pop(oldest_key, None)

    def _ensure_feature_samples(self, df: pd.DataFrame, *, inst_id: str, timeframe: str) -> None:
        if df is None:
            raise ValueError(f"{inst_id} {timeframe} 特征数据为空")
        rows = len(df)
        if rows < self.feature_min_samples:
            raise ValueError(
                f"{inst_id} {timeframe} 特征样本不足：{rows} < {self.feature_min_samples}，已跳过该标的。"
            )

    def _timeframe_cache_ttl(self, timeframe: str) -> float:
        tf = (timeframe or "").lower()
        try:
            if tf.endswith("m"):
                minutes = int(tf[:-1] or 0)
                if minutes >= 15:
                    return self._higher_tf_cache_ttl
            elif tf.endswith("h") or tf.endswith("d") or tf.endswith("w"):
                return self._higher_tf_cache_ttl
        except ValueError:
            pass
        return self._candle_cache_ttl

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
        trace_id: Optional[str],
        summary: str,
        strategy_output: StrategyOutput,
        signal: TradeSignal,
    ) -> None:
        try:
            ts_value = features.iloc[-1].get("ts", "")
            timestamp = str(ts_value)
            close_price = float(features.iloc[-1].get("close", 0.0) or 0.0)
            analysis_view = strategy_output.analysis_view
            record = DecisionRecord(
                timestamp=timestamp,
                inst_id=inst_id,
                timeframe=timeframe,
                analysis_action=analysis_view.action.value,
                analysis_confidence=analysis_view.confidence,
                analysis_reason=analysis_view.reason,
                strategy_action=signal.action.value,
                close_price=close_price,
                trace_id=trace_id,
            )
            self.decision_logger.log(record)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"记录决策失败: {exc}")

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
