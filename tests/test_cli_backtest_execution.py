"""CLI backtest 执行聚合测试。"""

from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace


def _load_execution():
    assert importlib.util.find_spec("cli_app.backtest_execution") is not None
    module = importlib.import_module("cli_app.backtest_execution")
    assert hasattr(module, "collect_backtest_records")
    assert hasattr(module, "collect_tuning_snapshot")
    return module


def _bundle():
    plugin_manager = object()
    return SimpleNamespace(
        okx=object(),
        engine=SimpleNamespace(
            leverage=3,
            strategy=SimpleNamespace(
                signal_generator=SimpleNamespace(plugin_manager=plugin_manager)
            ),
        ),
        settings=SimpleNamespace(runtime=SimpleNamespace(default_max_position=0.25)),
        _original_manager=plugin_manager,
    )


def _args():
    return SimpleNamespace(
        limit=150,
        warmup=50,
        initial_equity=10000.0,
        fee_rate=0.001,
        slippage_ratio=0.0,
        spread_ratio=0.0,
        max_hold_bars=0,
    )


def test_backtest_execution_module_exists() -> None:
    _load_execution()


def test_collect_backtest_records_skips_empty_features_and_uses_default_position(monkeypatch) -> None:
    execution = _load_execution()
    bundle = _bundle()
    run_calls = []

    def _build_features(_okx, inst_id, timeframe, limit):
        return SimpleNamespace(empty=(inst_id == "ETH-USDT-SWAP"))

    class _FakeResult:
        def to_dict(self):
            return {"summary": {"inst_id": "BTC-USDT-SWAP"}}

    def _run_single_backtest(**kwargs):
        run_calls.append(kwargs)
        return _FakeResult()

    monkeypatch.setattr(execution, "_build_features_for_backtest", _build_features)
    monkeypatch.setattr(
        execution,
        "_build_higher_timeframe_features_for_backtest",
        lambda _okx, inst_id, higher_timeframes, limit: {},
        raising=False,
    )
    monkeypatch.setattr(execution, "_run_single_backtest", _run_single_backtest)

    records = execution.collect_backtest_records(
        bundle=bundle,
        args=_args(),
        entries=[
            {"inst_id": "BTC-USDT-SWAP", "timeframe": "5m", "max_position": 0},
            {"inst_id": "ETH-USDT-SWAP", "timeframe": "15m", "max_position": 0.4},
        ],
    )

    assert records == [{"summary": {"inst_id": "BTC-USDT-SWAP"}}]
    assert len(run_calls) == 1
    assert run_calls[0]["max_position"] == 0.25
    assert run_calls[0]["inst_id"] == "BTC-USDT-SWAP"


def test_collect_backtest_records_passes_higher_timeframe_features_to_runner(monkeypatch) -> None:
    execution = _load_execution()
    bundle = _bundle()
    run_calls = []
    higher_features = {"1H": SimpleNamespace(empty=False)}

    monkeypatch.setattr(
        execution,
        "_build_features_for_backtest",
        lambda _okx, inst_id, timeframe, limit: SimpleNamespace(empty=False),
    )
    monkeypatch.setattr(
        execution,
        "_build_higher_timeframe_features_for_backtest",
        lambda _okx, inst_id, higher_timeframes, limit: higher_features,
        raising=False,
    )

    class _FakeResult:
        def to_dict(self):
            return {"summary": {"inst_id": "BTC-USDT-SWAP"}}

    def _run_single_backtest(**kwargs):
        run_calls.append(kwargs)
        return _FakeResult()

    monkeypatch.setattr(execution, "_run_single_backtest", _run_single_backtest)

    execution.collect_backtest_records(
        bundle=bundle,
        args=_args(),
        entries=[
            {
                "inst_id": "BTC-USDT-SWAP",
                "timeframe": "5m",
                "higher_timeframes": ("1H",),
                "max_position": 0.3,
            }
        ],
    )

    assert len(run_calls) == 1
    assert run_calls[0]["higher_timeframe_features"] == higher_features


def test_collect_tuning_snapshot_restores_plugin_manager_and_builds_scores(monkeypatch) -> None:
    execution = _load_execution()
    bundle = _bundle()
    original_manager = bundle.engine.strategy.signal_generator.plugin_manager

    monkeypatch.setattr(
        execution,
        "_build_features_for_backtest",
        lambda _okx, inst_id, timeframe, limit: SimpleNamespace(empty=False),
    )
    monkeypatch.setattr(
        execution,
        "_build_higher_timeframe_features_for_backtest",
        lambda _okx, inst_id, higher_timeframes, limit: {},
        raising=False,
    )
    monkeypatch.setattr(execution, "_market_regime_bucket", lambda features: "mid_vol")

    score_map = {"alpha": 0.6, "beta": 0.2}

    class _FakeResult:
        def __init__(self, name):
            self.summary = SimpleNamespace(total_trades=10, win_rate=0.5, net_pnl=100.0 if name == "alpha" else 50.0)
            self._name = name

        def to_dict(self):
            return {"summary": {"plugin": self._name}}

    class _FakeSignalPluginManager:
        def __init__(self, enabled_raw, weights_raw):
            self.enabled_raw = enabled_raw
            self.weights_raw = weights_raw

    def _run_single_backtest(**kwargs):
        manager = bundle.engine.strategy.signal_generator.plugin_manager
        name = manager.enabled_raw
        return _FakeResult(name)

    monkeypatch.setattr(execution, "SignalPluginManager", _FakeSignalPluginManager)
    monkeypatch.setattr(execution, "_run_single_backtest", _run_single_backtest)
    monkeypatch.setattr(execution, "_plugin_score", lambda summary, initial_equity: score_map[summary["plugin"]])

    snapshot = execution.collect_tuning_snapshot(
        bundle=bundle,
        args=_args(),
        entries=[{"inst_id": "BTC-USDT-SWAP", "timeframe": "5m", "max_position": 0.3}],
        names=["alpha", "beta"],
    )

    assert snapshot.scanned_instruments == 1
    assert snapshot.scores == {"alpha": 0.6, "beta": 0.2}
    assert snapshot.weights["alpha"] > snapshot.weights["beta"]
    assert snapshot.regime_score_buckets["mid_vol"]["alpha"] == [0.6]
    assert snapshot.regime_score_buckets["mid_vol"]["beta"] == [0.2]
    assert bundle.engine.strategy.signal_generator.plugin_manager is original_manager


def test_collect_tuning_snapshot_passes_higher_timeframe_features_to_runner(monkeypatch) -> None:
    execution = _load_execution()
    bundle = _bundle()
    run_calls = []
    higher_features = {"1H": SimpleNamespace(empty=False)}

    monkeypatch.setattr(
        execution,
        "_build_features_for_backtest",
        lambda _okx, inst_id, timeframe, limit: SimpleNamespace(empty=False),
    )
    monkeypatch.setattr(
        execution,
        "_build_higher_timeframe_features_for_backtest",
        lambda _okx, inst_id, higher_timeframes, limit: higher_features,
        raising=False,
    )
    monkeypatch.setattr(execution, "_market_regime_bucket", lambda features: "mid_vol")

    class _FakeResult:
        def __init__(self) -> None:
            self.summary = SimpleNamespace(total_trades=4, win_rate=0.5, net_pnl=12.0)

        def to_dict(self):
            return {"summary": {"plugin": "alpha"}}

    class _FakeSignalPluginManager:
        def __init__(self, enabled_raw, weights_raw):
            self.enabled_raw = enabled_raw
            self.weights_raw = weights_raw

    def _run_single_backtest(**kwargs):
        run_calls.append(kwargs)
        return _FakeResult()

    monkeypatch.setattr(execution, "SignalPluginManager", _FakeSignalPluginManager)
    monkeypatch.setattr(execution, "_run_single_backtest", _run_single_backtest)
    monkeypatch.setattr(execution, "_plugin_score", lambda summary, initial_equity: 0.3)

    snapshot = execution.collect_tuning_snapshot(
        bundle=bundle,
        args=_args(),
        entries=[
            {
                "inst_id": "BTC-USDT-SWAP",
                "timeframe": "5m",
                "higher_timeframes": ("1H",),
                "max_position": 0.3,
            }
        ],
        names=["alpha"],
    )

    assert snapshot.scanned_instruments == 1
    assert len(run_calls) == 1
    assert run_calls[0]["higher_timeframe_features"] == higher_features
