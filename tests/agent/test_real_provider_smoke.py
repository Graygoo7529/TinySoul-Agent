from __future__ import annotations

import os
from pathlib import Path

import pytest

from tinysoul.agent import Agent, UserTurnRequest
from tinysoul.kernel.loop.turn import TurnOutcome


pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        os.environ.get("TINYSOUL_RUN_REAL_LLM_APP") != "1",
        reason="real provider SDK smoke test is disabled",
    ),
]


async def test_configured_real_provider_completes_one_turn() -> None:
    configured_root = os.environ.get("TINYSOUL_REAL_PROJECT_ROOT", "")
    if not configured_root:
        pytest.fail(
            "TINYSOUL_REAL_PROJECT_ROOT must name an initialized, configured project"
        )
    root = Path(configured_root).expanduser().resolve()

    agent = await Agent.create(root, overrides={
        "reflection.schedule.enabled": False, "workspace.watch.enabled": False,
    })
    try:
        await agent.start()
        handle = await agent.submit_turn(UserTurnRequest("Reply with a short confirmation."))
        result = await handle.wait()
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.output is not None
    finally:
        await agent.shutdown()
