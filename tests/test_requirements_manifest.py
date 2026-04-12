from __future__ import annotations

from pathlib import Path


def _load_requirement_names() -> set[str]:
    names: set[str] = set()
    for raw in Path("requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split("==", 1)[0].strip().lower())
    return names


def test_requirements_manifest_matches_runtime_dependencies() -> None:
    assert _load_requirement_names() == {
        "loguru",
        "okx",
        "pandas",
        "python-dotenv",
        "pydantic",
        "pydantic-settings",
        "requests",
        "ta",
        "websocket-client",
    }
