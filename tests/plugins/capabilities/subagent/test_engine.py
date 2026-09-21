import asyncio
from pathlib import Path
import sys

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.jobs import JobRegistry, JobState
from tinysoul.kernel.loop.interaction.inbox import TurnInbox, WaitCondition, WaitReason
from tinysoul.plugins.capabilities.subagent.config import AgentTarget, SubagentSettings
from tinysoul.plugins.capabilities.subagent.engine import SubagentEngine
from tinysoul.plugins.capabilities.subagent.segments.connections import (
    ConnectionsSegment,
    ConnectionsRefresh,
)
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings


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
    jobs.bind_inbox("turn", inbox)
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
    segment = ConnectionsSegment(engine, "turn")
    try:
        connected = await engine.connect("turn", "user", "local")
        connection = str(connected["connection_id"])
        assert events[-1].target_id == "turn"
        assert segment.seal()["connections"] == []
        segment.install(await segment.prepare((ConnectionsRefresh(),)))
        assert connection in str(segment.seal())
        await segment.close()
        assert connection in str(engine.connections("turn"))
        first = await engine.delegate("turn", connection, "permission background")
        await asyncio.wait_for(
            inbox.wait_for_cycle(WaitCondition(WaitReason.EVENT, 0, job_id=first)), 5
        )
        snapshot = jobs.snapshot("turn", first)
        assert snapshot.state is JobState.WAITING_INPUT
        assert snapshot.pending_inputs[0].to_json()["kind"] == "permission"
        engine.backend("turn", first).respond(
            snapshot.pending_inputs[0].request_id, "yes_once"
        )
        await _settled(jobs, "turn", first)
        output = await engine.backend("turn", first).collect()
        assert "yes_once" in str(output) and "invocation 1; active 1" in str(output)
        second = await engine.delegate("turn", connection, "next")
        await _settled(jobs, "turn", second)
        assert second != first and "invocation 2; active 0" in str(
            await engine.backend("turn", second).collect()
        )
        await jobs.cleanup_turn("turn")
        await engine.close_turn("turn")
        reused = await engine.connect("next-turn", "user", "local")
        assert reused["connection_id"] == connection
        third = await engine.delegate("next-turn", connection, "fresh")
        await _settled(jobs, "next-turn", third)
        assert "session_2; invocation 1" in str(
            await engine.backend("next-turn", third).collect()
        )
        fourth = await engine.delegate("next-turn", connection, "wait_forever")
        await asyncio.sleep(0.1)
        stopped = await jobs.stop("next-turn", fourth, operations=JoinedOperations())
        assert stopped.state is JobState.CANCELLED
        fifth = await engine.delegate("next-turn", connection, "ignore_cancel")
        await asyncio.sleep(0.1)
        await jobs.stop("next-turn", fifth, operations=JoinedOperations())
        assert not jobs.has_unresolved("next-turn")
        assert "unavailable" in str(engine.connections("next-turn"))
        await jobs.cleanup_turn("next-turn")
        await engine.close_turn("next-turn")
    finally:
        await jobs.cleanup_turn("turn")
        await jobs.cleanup_turn("next-turn")
        await engine.close()
