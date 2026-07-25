from __future__ import annotations

from dataclasses import replace

import pytest

from tinysoul.action import ActionResultStatus
from tinysoul.context.trace import SealedTurnTrace
from tinysoul.loop import BusinessDay
from tinysoul.session.completion import project_turn_record
from tinysoul.session.errors import SessionInvariantError
from tinysoul.session.models import SessionActionOutcome, SessionOutputRecord

from .synthetic import SyntheticAction, completion


DAY = BusinessDay.parse("2026-07-25")


def test_completion_projects_typed_action_business_facts() -> None:
    source = completion(
        "turn_projection",
        ask="write the report",
        actions=(
            SyntheticAction(
                "workspace.write",
                request={"link": "workspace:report.md"},
                result={"written": True},
                references=("workspace:report.md",),
            ),
            SyntheticAction(
                "web.search",
                status=ActionResultStatus.FAILED,
                failure_reason="provider_unavailable",
            ),
        ),
    )

    record = project_turn_record(
        source,
        day=DAY,
        output=SessionOutputRecord(text="done"),
        exhausted=False,
    )

    assert record.ref == "session:turn/turn_projection"
    assert [item.outcome for item in record.actions] == [
        SessionActionOutcome.SUCCESS,
        SessionActionOutcome.FAILED,
    ]
    assert record.actions[0].result == {"written": True}
    assert record.actions[0].references == ("workspace:report.md",)
    assert record.actions[1].failure is not None
    assert record.actions[1].failure.reason == "provider_unavailable"


def test_completion_rejects_unpaired_action_evidence() -> None:
    source = completion(
        "turn_unpaired",
        actions=(SyntheticAction("workspace.read"),),
    )
    broken = replace(
        source,
        trace=SealedTurnTrace(
            turn_id=source.turn_id,
            entries=source.trace.entries[:-1],
        ),
    )

    with pytest.raises(SessionInvariantError, match="unpaired"):
        project_turn_record(
            broken,
            day=DAY,
            output=None,
            exhausted=True,
        )
