"""CLI 运行心跳文件测试。"""

from __future__ import annotations

from pathlib import Path

from cli_app.helpers import _read_runtime_heartbeat, _write_runtime_heartbeat


def test_runtime_heartbeat_roundtrip(tmp_path) -> None:
    path = Path(tmp_path) / "runtime_heartbeat.json"
    _write_runtime_heartbeat(
        path=path,
        status="running",
        cycle=3,
        exit_code=0,
        detail="",
    )

    payload = _read_runtime_heartbeat(path)
    assert payload is not None
    assert payload["status"] == "running"
    assert payload["cycle"] == 3
    assert payload["exit_code"] == 0
    assert "updated_at" in payload


def test_runtime_heartbeat_invalid_content_returns_none(tmp_path) -> None:
    path = Path(tmp_path) / "runtime_heartbeat.json"
    path.write_text("not-json", encoding="utf-8")
    assert _read_runtime_heartbeat(path) is None
