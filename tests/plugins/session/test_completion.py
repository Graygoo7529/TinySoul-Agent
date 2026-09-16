from __future__ import annotations

from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus

from dataclasses import replace

import pytest

from tinysoul.kernel.action import ActionResultStatus
from tinysoul.kernel.action.core.call import ExecutionState
from tinysoul.kernel.context.trace import SealedTurnTrace
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.session.completion import project_turn_record
from tinysoul.plugins.session.models import SessionActionOutcome, SessionOutputRecord

from .synthetic import SyntheticAction, completion


DAY = CalendarDay.parse("2026-07-25")


def test_completion_projects_typed_action_business_facts() -> None:
    source = completion(
        "turn_projection",
        ask="write the report",
        actions=(
            SyntheticAction(
                "workspace.create",
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
        status=TurnOutcomeStatus.ANSWERED,
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


def test_completion_does_not_reconstruct_actions_from_message_pairing() -> None:
    source = completion(
        "turn_unpaired",
        actions=(SyntheticAction("workspace.read"),),
    )
    broken = replace(
        source,
        trace=SealedTurnTrace(
            turn_id=source.turn_id,
            entries=source.trace.entries[:-1],
            actions=source.trace.actions,
        ),
    )

    record = project_turn_record(broken, day=DAY, output=None, exhausted=True, status=TurnOutcomeStatus.EXHAUSTED)
    assert len(record.actions) == 1
    assert record.actions[0].outcome is SessionActionOutcome.SUCCESS


@pytest.mark.parametrize("state", [
    ExecutionState.CANCELLED, ExecutionState.NOT_EXECUTED, ExecutionState.UNKNOWN,
])
def test_completion_preserves_interruption_without_fabricated_result(state) -> None:
    source = completion("turn_interrupted", actions=(SyntheticAction("workspace.create"),))
    source = replace(source, trace=replace(source.trace, actions=(
        replace(source.trace.actions[0], state=state, result=None),
    )))
    record = project_turn_record(source, day=DAY, output=None, exhausted=False, status=TurnOutcomeStatus.STOPPED)
    assert record.actions[0].outcome.value == state.value
    assert record.actions[0].failure is None
    assert record.actions[0].result == {}
