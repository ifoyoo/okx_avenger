"""CLI 单入口约束测试。"""

from __future__ import annotations

from pathlib import Path

import cli


def test_cli_main_dispatches_selected_handler(monkeypatch) -> None:
    calls: list[str] = []

    def fake_status(args) -> int:
        calls.append(args.command)
        return 17

    monkeypatch.setattr(cli, "cmd_status", fake_status)

    assert cli.main(["status"]) == 17
    assert calls == ["status"]


def test_okx_launcher_targets_cli_py() -> None:
    content = Path("okx").read_text(encoding="utf-8")

    assert '"${SCRIPT_DIR}/cli.py"' in content
    assert "main.py" not in content


def test_main_py_is_removed() -> None:
    assert not Path("main.py").exists()
