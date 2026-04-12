"""CLI backtest 存储辅助测试。"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def _load_storage():
    assert importlib.util.find_spec("cli_app.backtest_storage") is not None
    module = importlib.import_module("cli_app.backtest_storage")
    assert hasattr(module, "_serialize_backtest_record")
    assert hasattr(module, "_save_backtest_records")
    assert hasattr(module, "_load_backtest_records")
    return module


def test_backtest_storage_module_exists() -> None:
    _load_storage()


def test_serialize_backtest_record_normalizes_infinite_profit_factor() -> None:
    storage = _load_storage()
    payload = storage._serialize_backtest_record(
        {"summary": {"profit_factor": float("inf"), "inst_id": "BTC-USDT-SWAP"}}
    )

    assert payload["summary"]["profit_factor"] == "inf"
    assert payload["summary"]["inst_id"] == "BTC-USDT-SWAP"


def test_save_and_load_backtest_records_roundtrip(tmp_path) -> None:
    storage = _load_storage()
    storage.BACKTEST_DIR = Path(tmp_path)
    storage.BACKTEST_LATEST = storage.BACKTEST_DIR / "latest.json"

    records = [{"summary": {"inst_id": "BTC-USDT-SWAP", "profit_factor": float("inf")}}]
    path = storage._save_backtest_records(records)

    assert path.exists()
    assert storage.BACKTEST_LATEST.exists()
    assert storage._load_backtest_records(path) == [
        {"summary": {"inst_id": "BTC-USDT-SWAP", "profit_factor": "inf"}}
    ]
