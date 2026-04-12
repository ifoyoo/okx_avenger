from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

BACKTEST_DIR = Path("data/backtests")
BACKTEST_LATEST = BACKTEST_DIR / "latest.json"


def _serialize_backtest_record(record: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(record.get("summary") or {})
    if summary.get("profit_factor") == float("inf"):
        summary["profit_factor"] = "inf"
    output = dict(record)
    output["summary"] = summary
    return output


def _save_backtest_records(records: List[Dict[str, Any]]) -> Path:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "records": [_serialize_backtest_record(item) for item in records],
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKTEST_DIR / f"backtest-{stamp}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    with BACKTEST_LATEST.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def _load_backtest_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    records = payload.get("records") or []
    if not isinstance(records, list):
        return []
    return records
