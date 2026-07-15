from __future__ import annotations

import os
from pathlib import Path

import pytest

from tinysoul.app import cli


pytestmark = pytest.mark.skipif(
    os.environ.get("TINYSOUL_RUN_REAL_LLM_APP") != "1",
    reason="real provider App/CLI smoke test is disabled",
)


def test_configured_real_provider_completes_one_cli_turn() -> None:
    configured_root = os.environ.get("TINYSOUL_REAL_PROJECT_ROOT", "")
    if not configured_root:
        pytest.fail(
            "TINYSOUL_REAL_PROJECT_ROOT must name an initialized, configured project"
        )
    root = Path(configured_root).expanduser().resolve()

    result = cli.main(
        [
            "--root",
            str(root),
            "--once",
            "Reply with a short confirmation that the TinySoul App/CLI smoke test ran.",
        ]
    )

    assert result == 0
