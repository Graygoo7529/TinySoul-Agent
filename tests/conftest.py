"""Global pytest fixtures and configuration for TinySoul test suite."""

from pathlib import Path
from uuid import uuid4

import pytest

from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.action.handlers import bootstrap
from tinysoul.infra import CaptureSink, EventLogger, EventLevel
from tinysoul.context.workspace import Workspace


# -----------------------------------------------------------------------------
# Pytest configuration
# -----------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_api: marks tests that call real LLM APIs"
    )


# -----------------------------------------------------------------------------
# Shared fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def tmp_path() -> Path:
    """Create a Windows-sandbox-friendly temporary directory for tests."""
    base = Path.cwd() / ".pytest-local-tmp"
    base.mkdir(exist_ok=True)
    path = base / uuid4().hex
    path.mkdir()
    return path


@pytest.fixture
def bootstrapped_registry() -> ActionRegistry:
    """Return a fresh ActionRegistry with all built-in actions bootstrapped."""
    registry = ActionRegistry()
    bootstrap(registry)
    return registry


@pytest.fixture
def capture_logger():
    """Return an EventLogger with a CaptureSink for test assertions."""
    sink = CaptureSink()
    logger = EventLogger(level=EventLevel.DEBUG, sinks=[sink])
    return logger, sink


@pytest.fixture
def empty_workspace(tmp_path):
    """Return an empty Workspace backed by a real temporary directory."""
    return Workspace(workspace_location=str(tmp_path))


@pytest.fixture
def workspace_with_files(tmp_path):
    """Return a Workspace pre-populated with sample files."""
    (tmp_path / "readme.md").write_text("# Hello", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "numbers.csv").write_text("a,b\n1,2", encoding="utf-8")
    ws = Workspace(workspace_location=str(tmp_path))
    ws.scan()
    return ws
