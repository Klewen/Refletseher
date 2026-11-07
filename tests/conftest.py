from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="run tests that write to the physical MS-1565 keyboard",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-hardware") or os.environ.get("SCREENSYNC_HARDWARE") == "1":
        return
    skip = pytest.mark.skip(reason="hardware test: pass --run-hardware to enable")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def mock_backend():
    from screensync.device.mock import MockBackend

    return MockBackend()


@pytest.fixture
def tmp_appdata(tmp_path, monkeypatch):
    """Redirect every app data path into a temp folder."""
    monkeypatch.setenv("SCREENSYNC_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
