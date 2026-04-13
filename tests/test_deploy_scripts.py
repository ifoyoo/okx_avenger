"""Deployment script contract tests."""

from __future__ import annotations

from pathlib import Path
import subprocess


def test_local_deploy_script_exists_and_parses() -> None:
    script = Path("scripts/deploy_netcup.sh")

    assert script.exists()
    assert script.is_file()
    result = subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_remote_update_script_exists_and_parses() -> None:
    script = Path("scripts/update_vps.sh")

    assert script.exists()
    assert script.is_file()
    result = subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_local_deploy_script_pushes_and_can_sync_runtime_files() -> None:
    content = Path("scripts/deploy_netcup.sh").read_text(encoding="utf-8")

    assert "git push origin HEAD:${REMOTE_BRANCH}" in content
    assert "--sync-env" in content
    assert "--sync-watchlist" in content
    assert "scp" in content
    assert "scripts/update_vps.sh" in content


def test_remote_update_script_reinstalls_and_restarts_service() -> None:
    content = Path("scripts/update_vps.sh").read_text(encoding="utf-8")

    assert "pip install -r requirements.txt -c constraints.txt" in content
    assert "cli.py config-check" in content
    assert 'restart "${SERVICE_NAME}"' in content
    assert 'is-active "${SERVICE_NAME}"' in content
    assert "git pull --ff-only" in content
