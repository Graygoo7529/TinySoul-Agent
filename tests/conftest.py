from __future__ import annotations

from pathlib import Path
import shutil

import pytest


@pytest.fixture
def local_tmp(request: pytest.FixtureRequest) -> Path:
    safe_name = request.node.name.replace("[", "_").replace("]", "_")
    path = Path(".test-tmp") / safe_name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path

