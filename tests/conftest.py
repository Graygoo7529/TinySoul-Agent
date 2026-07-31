from __future__ import annotations

import os
from pathlib import Path
import tempfile
from uuid import uuid4

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_configured_run_root = os.environ.get("PYTEST_TINYSOUL_RUN_ROOT", "").strip()
if _configured_run_root:
    _TEST_RUN_ROOT = Path(_configured_run_root).expanduser().resolve()
else:
    _TEST_RUN_ROOT = (
        _REPOSITORY_ROOT
        / ".local-test"
        / "runs"
        / f"direct-{uuid4().hex}"
    ).resolve()

_TEMP_ROOT = _TEST_RUN_ROOT / "temp"
_LOCAL_APP_DATA_ROOT = _TEST_RUN_ROOT / "local-app-data"
for _directory in (_TEMP_ROOT, _LOCAL_APP_DATA_ROOT):
    _directory.mkdir(parents=True, exist_ok=True)

os.environ["PYTEST_TINYSOUL_RUN_ROOT"] = str(_TEST_RUN_ROOT)
os.environ["TEMP"] = str(_TEMP_ROOT)
os.environ["TMP"] = str(_TEMP_ROOT)
os.environ["TMPDIR"] = str(_TEMP_ROOT)
os.environ["LOCALAPPDATA"] = str(_LOCAL_APP_DATA_ROOT)
tempfile.tempdir = str(_TEMP_ROOT)


def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp is None:
        config.option.basetemp = str(_TEST_RUN_ROOT / "pytest")


@pytest.fixture
def local_tmp(tmp_path: Path) -> Path:
    return tmp_path
