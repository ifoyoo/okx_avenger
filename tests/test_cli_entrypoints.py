"""CLI 单入口约束测试。"""

from __future__ import annotations

import argparse
from pathlib import Path

import cli


def test_cli_main_dispatches_selected_handler(monkeypatch) -> None:
    parser = argparse.ArgumentParser()
    parser.set_defaults(command="status")

    def fake_status(args) -> int:
        assert args.command == "status"
        return 17

    parser.set_defaults(func=fake_status)
    monkeypatch.setattr(cli, "build_parser", lambda: parser)

    assert cli.main([]) == 17


def test_okx_launcher_targets_cli_py() -> None:
    content = Path("okx").read_text(encoding="utf-8")

    assert '"${SCRIPT_DIR}/cli.py"' in content
    assert "main.py" not in content


def test_main_py_is_removed() -> None:
    assert not Path("main.py").exists()
