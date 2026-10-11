import asyncio
from pathlib import Path
import sys
import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.jobs import JobRegistry, JobState
from tinysoul.kernel.loop.interaction.inbox import (
    InboxKind,
    TurnInbox,
    WaitCondition,
    WaitReason,
    WakeReason,
)
from tinysoul.plugins.capabilities.subagent.config import AgentTarget, SubagentSettings
from tinysoul.plugins.capabilities.subagent.engine import SubagentEngine
from tinysoul.plugins.capabilities.subagent.failures import SubagentFailure, SubagentRequestError
from tinysoul.plugins.capabilities.subagent.segments.connections import (
    ConnectionsSegment,
    ConnectionsRefresh,
)
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings

TURN_ID = "2026-07-12/1"
NEXT_TURN_ID = "2026-07-12/2"
DAY_TURN_ID = "2026-07-13/1"


async def _settled(jobs: JobRegistry, turn: str, identity: str) -> None:
    async with asyncio.timeout(5):
        while not jobs.snapshot(turn, identity).state.terminal or jobs.has_unresolved(
            turn
        ):
            await asyncio.sleep(0.01)


async def test_real_acp_permission_same_turn_reuse_and_new_turn_isolation(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    jobs, inbox = JobRegistry(), TurnInbox()
    jobs.bind_inbox(TURN_ID, inbox)
    engine = SubagentEngine(
        SubagentSettings(
            stop_timeout_seconds=0.2,
            agents=(
                AgentTarget(
                    "local",
                    enabled=True,
                    command=sys.executable,
                    args=(str(Path(__file__).with_name("fixture_agent.py")),),
                ),
            ),
        ),
        jobs=jobs,
        workspace=workspace,
        environment={},
    )
    events: list[EnvironmentEvent] = []

    async def publish(event: EnvironmentEvent) -> EventReceipt:
        events.append(event)
        return EventReceipt(len(events), event.event_id, True)

    await engine.start(publish)
    segment = ConnectionsSegment(engine, TURN_ID)
    try:
        connected = await engine.connect(TURN_ID, "user", "local")
        connection = str(connected["connection_id"])
        assert events[-1].target_id == TURN_ID
        assert segment.seal()["connections"] == []
        segment.install(await segment.prepare((ConnectionsRefresh(),)))
        assert connection in str(segment.seal())
        await segment.close()
        assert connection in str(engine.connections(TURN_ID))
        first = await engine.delegate(TURN_ID, connection, "permission background")
        readiness = await asyncio.wait_for(
            inbox.wait_for_cycle(
                WaitCondition(WaitReason.EVENT, 0, event_kind=InboxKind.JOB)
            ),
            5,
        )
        assert readiness.reason is WakeReason.JOB
        assert readiness.wake_job_id == first
        snapshot = jobs.snapshot(TURN_ID, first)
        assert snapshot.state is JobState.WAITING_INPUT
        assert snapshot.pending_inputs[0].to_json()["kind"] == "permission"
        engine.backend(TURN_ID, first).respond(
            snapshot.pending_inputs[0].request_id, "yes_once"
        )
        await _settled(jobs, TURN_ID, first)
        output = await engine.backend(TURN_ID, first).collect()
        assert "yes_once" in str(output) and "invocation 1; active 1" in str(output)
        second = await engine.delegate(TURN_ID, connection, "next")
        await _settled(jobs, TURN_ID, second)
        assert second != first and "invocation 2; active 0" in str(
            await engine.backend(TURN_ID, second).collect()
        )
        await jobs.cleanup_turn(TURN_ID)
        await engine.close_turn(TURN_ID)
        reused = await engine.connect(NEXT_TURN_ID, "user", "local")
        assert reused["connection_id"] == connection
        third = await engine.delegate(NEXT_TURN_ID, connection, "fresh")
        await _settled(jobs, NEXT_TURN_ID, third)
        assert "session_2; invocation 1" in str(
            await engine.backend(NEXT_TURN_ID, third).collect()
        )
        await jobs.cleanup_turn(NEXT_TURN_ID)
        await engine.close_turn(NEXT_TURN_ID)
        await engine.release_day()
        assert engine.connections(NEXT_TURN_ID)["connections"] == []
        with pytest.raises(SubagentRequestError) as stale:
            await engine.delegate(DAY_TURN_ID, connection, "retired connection")
        assert stale.value.reason is SubagentFailure.INVALID_REQUEST
        connected = await engine.connect(DAY_TURN_ID, "user", "local")
        assert connected["connection_id"] != connection
        connection = str(connected["connection_id"])
        fresh = await engine.delegate(DAY_TURN_ID, connection, "fresh day")
        await _settled(jobs, DAY_TURN_ID, fresh)
        assert "session_1; invocation 1" in str(
            await engine.backend(DAY_TURN_ID, fresh).collect()
        )
        fourth = await engine.delegate(DAY_TURN_ID, connection, "wait_forever")
        await asyncio.sleep(0.1)
        stopped = await jobs.stop(DAY_TURN_ID, fourth, operations=JoinedOperations())
        assert stopped.state is JobState.CANCELLED
        fifth = await engine.delegate(DAY_TURN_ID, connection, "ignore_cancel")
        await asyncio.sleep(0.1)
        await jobs.stop(DAY_TURN_ID, fifth, operations=JoinedOperations())
        assert not jobs.has_unresolved(DAY_TURN_ID)
        assert "unavailable" in str(engine.connections(DAY_TURN_ID))
        await jobs.cleanup_turn(DAY_TURN_ID)
        await engine.close_turn(DAY_TURN_ID)
    finally:
        await jobs.cleanup_turn(TURN_ID)
        await jobs.cleanup_turn(NEXT_TURN_ID)
        await jobs.cleanup_turn(DAY_TURN_ID)
        await engine.close()
