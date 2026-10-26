from __future__ import annotations
import asyncio
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from tinysoul.agent import (
    AgentClosedError,
    AgentServiceStaleError,
    HomeService,
    TurnState,
    UserTurnRequest,
)
from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.json import to_json_object
from tinysoul.infra.process import (
    ManagedProcess,
    ManagedProcessRequest,
    ManagedProcessRunner,
)
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.interaction.inbox import WaitReason
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.registration import RegistrationError
from tinysoul.llm.protocol.responses import RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.home.services import HomeReviewService
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.plugins.memory.services import MemoryKnowledgeService
from tinysoul.plugins.reflection import (
    ReflectionRequest,
    ReflectionScope,
    ReflectionTrigger,
)
from tinysoul.plugins.workspace import WorkspaceEngine
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace.storage.reconcile import (
    WorkspaceReconcileResult,
    WorkspaceReconcileStatus,
)
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tests.agent.support import (
    _Clock,
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


async def test_sdk_completed_facts_are_inspectable_until_daily_archive(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    llm.release.set()

    def result(call: ToolCallRecord) -> TaskResult:
        return TaskResult.success(
            raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
            answer=None,
            tool_calls=(call,),
        )

    select = ToolCallRecord(
        "select", "select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL
    )
    llm.results.extendleft(
        reversed(
            (
                result(select),
                result(
                    ToolCallRecord(
                        "wait",
                        "core.wait",
                        {"event_kind": "event", "event_id": "wake"},
                        ToolKind.ACTION,
                    )
                ),
            )
        )
    )
    clock = _Clock()
    agent = await _create(tmp_path, llm, clock=clock)
    await agent.start()
    try:
        first = await agent.submit_turn(UserTurnRequest("first request"))
        async with asyncio.timeout(5):
            while first.wait_reason is None:
                assert not first.done
                await asyncio.sleep(0.01)
        await agent.publish(
            EnvironmentEvent(EventKind.EVENT, {"notice": "event-marker"}, "wake")
        )
        await agent.append_input(
            first.request_id, "additional evidence", input_id="extra"
        )
        completed = await asyncio.wait_for(first.wait(), 5)
        assert isinstance(completed.outcome, TurnOutcome) and completed.outcome.answered
        llm.results.extend(
            (
                result(select),
                result(
                    ToolCallRecord(
                        "inspect",
                        "core.context.inspect",
                        {"ref": f"session:turn/{first.turn_id}"},
                        ToolKind.ACTION,
                    )
                ),
                *_LLM().results,
            )
        )
        second = await agent.submit_turn(UserTurnRequest("review the preceding work"))
        review = await asyncio.wait_for(second.wait(), 5)
        assert isinstance(review.outcome, TurnOutcome) and review.outcome.answered
        completion = review.outcome.context_completion
        assert completion is not None
        inspection = next(
            item
            for item in completion.trace.actions
            if item.call.action_name == "core.context.inspect"
        )
        assert inspection.result is not None
        assert "additional evidence" in str(inspection.result.payload)
        assert "event-marker" in str(inspection.result.payload)
        # The next decision task receives the full result before pressure may fold it.
        from tinysoul.runtime import CyclePhase, RunLevel

        assert any(
            "event-marker" in str(call.messages)
            for call in llm.calls
            if (phase := call.scope.nearest(RunLevel.PHASE)) is not None
            and phase.name == CyclePhase.PHASE1.value
        )
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        llm.results.extend(_LLM().results)
        following = await agent.submit_turn(UserTurnRequest("new day"))
        new = await asyncio.wait_for(following.wait(), 5)
        assert isinstance(new.outcome, TurnOutcome)
        assert new.outcome.active_day == clock.today()
        assert f"session:turn/{first.turn_id}" not in str(llm.calls[-3].messages)
        from tinysoul.plugins.session.records.store import SessionStore

        archive = next((tmp_path / "project" / "archive").glob("*/session"))
        archived = SessionStore(root=archive).load_record(
            f"session:turn/{first.turn_id}"
        )
        assert any(item.ref.endswith("#input/1") for item in archived.timeline)
        assert "event-marker" in str(archived.notes)
    finally:
        await agent.shutdown()


async def test_session_organize_updates_next_cycle_and_survives_restart_until_day_switch(
    tmp_path: Path,
) -> None:
    from tinysoul.agent import SessionService
    from tinysoul.plugins.session.services import SessionOrganizeService
    from tinysoul.runtime import CyclePhase, RunLevel

    llm = _LLM()
    llm.release.set()
    clock = _Clock()
    agent = await _create(tmp_path, llm, clock=clock)
    await agent.start()
    try:
        prior: list[str] = []
        for index in range(3):
            if index:
                llm.results.extend(_LLM().results)
            handle = await agent.submit_turn(UserTurnRequest(f"prior question {index}"))
            assert (
                await asyncio.wait_for(handle.wait(), 5)
            ).status is TurnOutcomeStatus.ANSWERED
            prior.append(f"session:turn/{handle.turn_id}")
        for name, params, kind in (
            ("select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL),
            (
                "core.session.organize",
                {
                    "scope_refs": prior,
                    "upsert_nodes": [
                        {
                            "ref": "local:topic",
                            "kind": "thread",
                            "title": "Shared topic",
                            "body": "The three requests advance the same investigation",
                            "source_refs": prior,
                        }
                    ],
                    "upsert_edges": [
                        {
                            "ref": f"local:member_{index}",
                            "source": "local:topic",
                            "target": ref,
                            "relation": "covers",
                            "body": "Part of the investigation",
                            "source_refs": [ref],
                        }
                        for index, ref in enumerate(prior)
                    ],
                },
                ToolKind.ACTION,
            ),
            ("select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL),
            ("core.context.inspect", {"ref": "session:topics"}, ToolKind.ACTION),
        ):
            call = ToolCallRecord(name, name, to_json_object(params), kind)
            llm.results.append(
                TaskResult.success(
                    raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                    answer=None,
                    tool_calls=(call,),
                )
            )
        llm.results.extend(_LLM().results)
        review = await agent.submit_turn(UserTurnRequest("organize our conversation"))
        finished = await asyncio.wait_for(review.wait(), 8)
        assert finished.status is TurnOutcomeStatus.ANSWERED
        assert isinstance(finished.outcome, TurnOutcome)
        facts = finished.outcome.context_completion
        assert facts is not None
        organized = next(
            item
            for item in facts.trace.actions
            if item.call.action_name == "core.session.organize"
        )
        assert (
            organized.result is not None and organized.result.status.value == "success"
        )
        decisions = [
            call
            for call in llm.calls
            if (turn := call.scope.nearest(RunLevel.TURN)) is not None
            and turn.name == review.turn_id
            and (phase := call.scope.nearest(RunLevel.PHASE)) is not None
            and phase.name == CyclePhase.PHASE1.value
        ]
        assert len(decisions) == 3
        assert (
            len(
                [
                    call
                    for call in llm.calls
                    if (turn := call.scope.nearest(RunLevel.TURN)) is not None
                    and turn.name == review.turn_id
                ]
            )
            == 7
        )  # Three phase pairs + the answer task.
        assert "Shared topic" not in str(decisions[0].messages)
        assert "Shared topic" in str(decisions[1].messages)
        for index in range(3):
            session_messages = tuple(
                message
                for message in decisions[1].messages.messages
                if message.label.startswith("session:")
            )
            assert str(session_messages).count(f"prior question {index}") == 1
        service = agent.services.get(SessionService)
        assert not hasattr(service, "organize")
        from tinysoul.kernel.retrieval.contracts import (
            QuerySource,
            RetrievalRequest,
            TextQuery,
        )

        search_page = await service.search(
            RetrievalRequest(QuerySource("session", TextQuery("prior question 0")))
        )
        search_items = [*search_page.items]
        while search_page.continuation:
            search_page = await service.search(search_page.continuation)
            search_items.extend(search_page.items)
        assert search_items and any(
            "prior question 0" in fragment.text
            for item in search_items
            for fragment in item.fragments
        )
        with pytest.raises(RegistrationError):
            agent.services.get(SessionOrganizeService)
        for scenario in ("user", "home_reflection", "memory_reflection"):
            actions = (await agent.action_catalog(scenario=scenario))["actions"]
            assert isinstance(actions, list)
            organize = next(
                item
                for item in actions
                if isinstance(item, dict) and item.get("id") == "core.session.organize"
            )
            assert isinstance(organize, dict)
            assert organize["granted"] is (scenario == "user")
            assert organize["available"] is (scenario == "user")
        assert "Shared topic" in str(
            (await service.inspect("session:topics")).to_json()
        )
        await agent.restart()
        service = agent.services.get(SessionService)
        assert "Shared topic" in str(
            (await service.inspect("session:topics")).to_json()
        )
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        llm.results.extend(_LLM().results)
        next_day = await agent.submit_turn(UserTurnRequest("new day"))
        assert (
            await asyncio.wait_for(next_day.wait(), 5)
        ).status is TurnOutcomeStatus.ANSWERED
        assert "Shared topic" not in str(
            (
                await agent.services.get(SessionService).inspect("session:topics")
            ).to_json()
        )
        from tinysoul.plugins.session.annotations.store import AnnotationStore

        archive = next((tmp_path / "project" / "archive").glob("*/session"))
        assert AnnotationStore(archive).load().nodes[0].title == "Shared topic"
    finally:
        await agent.shutdown()


async def test_day_bound_service_rejects_stale_write_and_restart_closes_old_services(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    agent = await _create(tmp_path, _LLM(), clock=clock)
    await agent.start()
    try:
        previous = agent.services.get(WorkspaceService)
        home = agent.services.get(HomeService)
        for facade in (HomeReviewService, MemoryKnowledgeService, MemoryEngine):
            with pytest.raises(RegistrationError):
                agent.services.get(facade)
        assert not hasattr(home, "resolve_review")
        await previous.write_text("workspace:same.txt", "old day")
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        with pytest.raises(AgentServiceStaleError):
            await previous.write_text("workspace:same.txt", "wrong day", overwrite=True)
        current = agent.services.get(WorkspaceService)
        assert current is not previous
        assert not await current.write_target_exists("workspace:same.txt")
        await current.write_text("workspace:same.txt", "new day")
        assert (await current.read_text("workspace:same.txt")).text == "new day"
        await home.default_background_refs()
        await agent.restart()
        with pytest.raises(AgentClosedError):
            await current.snapshot()
        with pytest.raises(AgentClosedError):
            await home.default_background_refs()
        assert (
            await agent.services.get(WorkspaceService).read_text("workspace:same.txt")
        ).text == "new day"
    finally:
        await agent.shutdown()


async def test_execution_is_stopped_before_queued_next_day_work_can_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes: list[ManagedProcess] = []
    start = ManagedProcessRunner.start
    reconcile = WorkspaceEngine.reconcile
    incomplete_delivered = False

    def discover(self: WorkspaceEngine) -> WorkspaceReconcileResult:
        nonlocal incomplete_delivered
        result = reconcile(self)
        if not incomplete_delivered and processes and processes[0].running():
            incomplete_delivered = True
            return replace(result, status=WorkspaceReconcileStatus.INCOMPLETE)
        return result

    def capture(
        self: ManagedProcessRunner,
        request: ManagedProcessRequest,
        *,
        capture_root: Path | None = None,
    ) -> ManagedProcess:
        process = start(self, request, capture_root=capture_root)
        processes.append(process)
        return process

    monkeypatch.setattr(ManagedProcessRunner, "start", capture)
    monkeypatch.setattr(WorkspaceEngine, "reconcile", discover)
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_execution",
                "select_action_domains",
                {"domains": ["execution"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "start",
                "execution.start",
                {
                    "interpreter": "python",
                    "source_ref": "workspace:long.py",
                    "interactive": True,
                },
                ToolKind.ACTION,
            ),
            ToolCallRecord(
                "select_question",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "ask", "core.ask", {"question": "Continue this job?"}, ToolKind.ACTION
            ),
        )
    ):
        llm.results.appendleft(
            TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None,
                tool_calls=(call,),
            )
        )
    llm.release.set()
    clock = _Clock()
    agent = await _create(tmp_path, llm, clock=clock)
    await agent.start()
    try:
        await agent.patch_config(
            (
                ConfigMutation(
                    source_id="project:configs/execution.toml",
                    path="execution.enabled",
                    op="set",
                    value=True,
                ),
                ConfigMutation(
                    source_id="project:configs/execution.toml",
                    path="execution.interpreters.python.executable",
                    op="set",
                    value=sys.executable,
                ),
            )
        )
        await agent.reload_config()
        workspace = agent.services.get(WorkspaceService)
        await workspace.write_text(
            "workspace:long.py",
            (
                "import subprocess,sys\n"
                "subprocess.Popen([sys.executable, '-c', "
                '"import threading; from pathlib import Path; '
                "f = Path('old-day.txt').open('w', encoding='utf-8'); "
                "f.write('preserved'); f.flush(); threading.Event().wait(15)\"], "
                "stdin=subprocess.DEVNULL)\n"
                "sys.stdin.read()\n"
            ),
        )
        active = await agent.submit_turn(UserTurnRequest("run and wait"))
        root = tmp_path / "project"
        async with asyncio.timeout(8):
            while active.wait_reason is not WaitReason.INPUT or not tuple(
                (root / "runtime" / "workspace").rglob("old-day.txt")
            ):
                assert not active.done
                await asyncio.sleep(0.01)
        assert incomplete_delivered and len(processes) == 1 and processes[0].running()
        clock.value = datetime(2026, 9, 16, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
        queued = await agent.submit_turn(UserTurnRequest("next day"))
        assert queued.state is TurnState.QUEUED
        assert (await workspace.read_text("workspace:long.py")).text
        await agent.cancel_request(active.request_id)
        cancelled = await asyncio.wait_for(active.wait(), 8)
        assert isinstance(cancelled.outcome, TurnOutcome)
        assert cancelled.outcome.status is TurnOutcomeStatus.CANCELLED
        next_result = await asyncio.wait_for(queued.wait(), 8)
        assert (
            isinstance(next_result.outcome, TurnOutcome)
            and next_result.outcome.answered
        )
        assert next_result.outcome.active_day == CalendarDay.parse("2026-09-16")
        assert not processes[0].running()
        assert not tuple((root / "runtime" / "workspace").rglob("old-day.txt"))
        artifacts = tuple((root / "archive").rglob("old-day.txt"))
        assert (
            len(artifacts) == 1
            and artifacts[0].read_text(encoding="utf-8") == "preserved"
        )
        with pytest.raises(AgentServiceStaleError):
            await workspace.snapshot()
    finally:
        await agent.shutdown()


async def test_request_identity_and_daily_turn_sequence_survive_restart(
    tmp_path: Path,
) -> None:
    llm, clock = _LLM(), _Clock()
    agent = await _create(tmp_path, llm, clock=clock)
    await agent.start()
    try:
        first = await agent.submit_turn(
            UserTurnRequest("first", request_id="request-first")
        )
        await asyncio.wait_for(llm.started.wait(), 5)
        assert first.request_id == "request-first" and first.turn_id == "2026-09-15/1"
        queued = await agent.submit_turn(
            UserTurnRequest("queued", request_id="request-queued")
        )
        assert queued.turn_id is None
        await agent.cancel_request(queued.request_id)
        assert (await queued.wait()).turn_id is None
        llm.release.set()
        assert (await first.wait()).status is TurnOutcomeStatus.ANSWERED
        await agent.restart()
        llm.results.extend(_LLM().results)
        second = await agent.submit_turn(UserTurnRequest("second"))
        assert (await second.wait()).turn_id == "2026-09-15/2"
        reflection = await agent.submit_turn(
            ReflectionRequest(
                scope=ReflectionScope.HOME, trigger=ReflectionTrigger.MANUAL
            )
        )
        assert (await reflection.wait()).turn_id == "2026-09-15/3"
        assert sorted(
            path.name
            for path in (tmp_path / "project/runtime/session/turns").glob("*.json")
        ) == ["1.json", "2.json"]
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        llm.results.extend(_LLM().results)
        new_day = await agent.submit_turn(UserTurnRequest("new day"))
        assert (await new_day.wait()).turn_id == "2026-09-16/1"
    finally:
        llm.release.set()
        await agent.shutdown()
