from __future__ import annotations

from tinysoul.infra.concurrency import CleanupDiagnostic

import asyncio
from datetime import date
import pytest
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event
from typing import cast

from tinysoul.kernel.context import ContextEngine, ContextEngineBuilder
from tinysoul.kernel.context.errors import ContextContractError
from tinysoul.kernel.context.segments import TurnInfo
from tinysoul.plugins.workspace.projection import (
    WorkspaceSegment,
    workspace_segment_registration,
)
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.kernel.loop import (
    TurnCompletion,
    TurnCompletionPipeline,
    PhaseFailure,
    TurnOutcomeStatus,
    TurnOutput,
    TurnPreparationPipeline,
    TurnPreparationRequest,
    TurnSettings,
)
from tinysoul.kernel.loop.cycle import CycleOutcome, CycleRunner
from tinysoul.kernel.loop.trap_handlers import (
    BudgetSuspendTrapHandler,
    EndFrameTrapHandler,
)
from tinysoul.kernel.loop.failures import LOOP_BUDGET_REQUIRED
from tinysoul.kernel.loop.interaction.inbox import (
    InboxKind,
    InboxRecord,
    TurnInbox,
    WaitReason,
)
from tinysoul.kernel.loop.interaction.inbox import QuestionRequest
from tinysoul.kernel.loop.turn import TurnRunner
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.session import SessionEngine, SessionSettings
from tinysoul.plugins.session.projection import SessionTurnCompletionHandler
from tinysoul.plugins.session.records.store import SessionStore
from tinysoul.plugins.session.records.models import SessionTurnRecord
from tinysoul.plugins.session.errors import SessionIOError
from tinysoul.runtime import (
    CyclePhase,
    ObservationEvent,
    ObservationLevel,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTransferInterrupt,
    RuntimeException,
    RuntimeTrap,
    Signal,
    SignalBus,
    TrapHandlerRegistry,
)

DAY = CalendarDay.parse("2026-07-12")


async def test_task_cancellation_seals_context_and_runs_completion_before_propagating() -> (
    None
):
    context = ContextEngineBuilder(system_text="test").build()
    entered = asyncio.Event()
    records: list[TurnCompletion] = []

    class WaitingCycle:
        async def run(self, **kwargs: object) -> CycleOutcome:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    class Recorder:
        async def handle(self, completion: TurnCompletion) -> None:
            records.append(completion)

    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, WaitingCycle()),
        settings=TurnSettings(),
        completion_pipeline=TurnCompletionPipeline((Recorder(),)),
    )
    running = asyncio.create_task(
        runner.run("question", active_day=DAY, scope=_agent_scope())
    )
    async with asyncio.timeout(2.0):
        await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert not context.turn_active
    assert runner.active_scope is None
    assert len(records) == 1 and records[0].output is None


@pytest.mark.parametrize("resolved_transfer", [False, True])
async def test_unwinding_turn_boundary_still_seals_and_records(
    resolved_transfer: bool,
) -> None:
    context = ContextEngineBuilder(system_text="test").build()
    recorder = _CompletionRecorder([])
    scope = _agent_scope()
    program = scope.current()
    assert program is not None
    transfer = RuntimeTransfer.end(program)

    class BrokenCycle:
        async def run(self, **kwargs: object) -> CycleOutcome:
            if resolved_transfer:
                raise RuntimeTransferInterrupt(transfer)
            raise RuntimeError("private implementation details")

    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, BrokenCycle()),
        settings=TurnSettings(),
        completion_pipeline=TurnCompletionPipeline(recorder=recorder),
    )
    result = await runner.run("question", active_day=DAY, scope=scope)
    assert not context.turn_active
    assert runner.active_scope is None
    assert len(recorder.completions) == 1
    if resolved_transfer:
        assert result.transfer is transfer
        assert result.status is TurnOutcomeStatus.STOPPED
    else:
        assert result.status is TurnOutcomeStatus.FAILED
        assert result.failure is not None
        assert result.failure.kind == "loop.internal_failure"
        assert "private implementation details" not in result.failure.message


@dataclass
class _EndFailingContext:
    active: bool = False
    aborted: int = 0

    @property
    def turn_active(self) -> bool:
        return self.active

    def begin_turn(self, user_input: str) -> str:
        self.active = True
        return "turn_1"

    async def open_segments(self, day: date) -> None:
        pass

    def end_turn(self) -> object:
        raise ContextContractError("summary failed")

    def abort_turn(self) -> None:
        self.active = False
        self.aborted += 1

    async def close_segments(self) -> tuple[CleanupDiagnostic, ...]:
        return ()

    def consume_signals(self, bus: SignalBus) -> tuple[object, ...]:
        return ()


class _AnsweredCycleRunner:
    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        frame = scope.nearest(RunLevel.TURN)
        assert frame is not None
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


class _ProgramEndCycleRunner:
    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        frame = scope.nearest(RunLevel.AGENT)
        assert frame is not None
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


@dataclass
class _CountingCycleRunner:
    calls: int = 0

    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        self.calls += 1
        frame = scope.nearest(RunLevel.TURN)
        assert frame is not None
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


@dataclass
class _RetryTurnPreparation:
    calls: int = 0

    async def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        self.calls += 1
        if self.calls == 1:
            frame = request.scope.nearest(RunLevel.TURN)
            assert frame is not None
            raise RuntimeTransferInterrupt(RuntimeTransfer.retry(frame))
        return ()


class _EndProgramPreparation:
    async def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        frame = request.scope.nearest(RunLevel.AGENT)
        assert frame is not None
        raise RuntimeTransferInterrupt(RuntimeTransfer.end(frame))


@dataclass
class _CompletionRecorder:
    completions: list[TurnCompletion]
    timeline: list[str] | None = None

    async def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)
        if self.timeline is not None:
            self.timeline.append("completion")


@dataclass
class _RecordingObservations:
    events: list[ObservationEvent]
    timeline: list[str]

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)
        self.timeline.append(event.name)


class _OutputCycleRunner:
    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            completion={"kind": "answer"},
        )


class _EmptyCycleRunner:
    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        return CycleOutcome(cycle_id=f"cycle_{cycle_index}")


@dataclass
class _Phase1FailureCycleRunner:
    calls: int = 0
    feedbacks: list[tuple[str, ...]] = field(default_factory=list)

    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        phase_feedback: tuple[str, ...] = (),
        **_kwargs: object,
    ) -> CycleOutcome:
        self.calls += 1
        self.feedbacks.append(tuple(phase_feedback))
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            phase_failure=PhaseFailure(
                phase=CyclePhase.PHASE1,
                reason="framework_task_failure",
                feedback=("shared feedback", f"attempt {self.calls} feedback"),
            ),
        )


class _CompletionCycleRunner:
    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            completion={
                "kind": "reflection",
                "result_id": "reflection_1",
                "task": "home",
            },
        )


@dataclass
class _CountingEmptyCycleRunner:
    calls: int = 0

    async def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        **_kwargs: object,
    ) -> CycleOutcome:
        self.calls += 1
        return CycleOutcome(cycle_id=f"cycle_{cycle_index}")


@dataclass
class _TurnActivity:
    remaining: int
    cleanup_calls: int = 0

    def bind_inbox(self, turn_id, inbox) -> None:
        pass

    def sync(self, turn_id, *, bus, scope) -> None:
        pass

    def has_unresolved(self, turn_id) -> bool:
        return False

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        assert turn_id
        self.cleanup_calls += 1
        return ()


class _FailingTurnActivity(_TurnActivity):
    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        await super().cleanup_turn(turn_id)
        return (CleanupDiagnostic("turn.activity", "OSError"),)


class _FailingCompletion:
    async def handle(self, completion: TurnCompletion) -> None:
        raise RuntimeException(
            reason=RUNTIME_TURN_END,
            message="Session completion failed.",
            payload={"module": "session", "kind": "session.io_failed"},
        )


async def test_turn_runner_captures_end_turn_failure_and_aborts_context() -> None:
    context = _EndFailingContext()
    runner = TurnRunner(
        context=cast(ContextEngine, context),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _AnsweredCycleRunner()),
        settings=TurnSettings(max_cycles=1),
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.context_completion is None
    assert context.turn_active is False
    assert context.aborted == 1
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.TURN
    assert outcome.status is TurnOutcomeStatus.FAILED
    assert outcome.failure is not None
    assert outcome.failure.module == "context"


async def test_turn_runner_keeps_existing_program_transfer_when_end_turn_fails() -> (
    None
):
    context = _EndFailingContext()
    runner = TurnRunner(
        context=cast(ContextEngine, context),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _ProgramEndCycleRunner()),
        settings=TurnSettings(max_cycles=1),
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert context.turn_active is False
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.AGENT
    assert outcome.status is TurnOutcomeStatus.FAILED


async def test_turn_completion_pipeline_receives_summary_and_output() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    bus = SignalBus()
    timeline: list[str] = []
    recorder = _CompletionRecorder([], timeline)
    observations = _RecordingObservations([], timeline)
    runner = TurnRunner(
        context=context,
        bus=bus,
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        completion_to_output=lambda _completion: TurnOutput(
            text="done",
            result_id="answer_1",
        ),
        completion_pipeline=TurnCompletionPipeline((recorder,)),
        observations=observations,
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.answered is True
    assert outcome.transfer is None
    assert len(recorder.completions) == 1
    completion = recorder.completions[0]
    assert completion.context_completion.inputs[0].text == "hello"
    assert completion.context_completion.trace.entries == ()
    assert completion.output is not None
    assert completion.output.text == "done"
    assert completion.active_day == DAY
    output_event = next(
        event for event in observations.events if event.name == "turn.output"
    )
    assert output_event.payload["text"] == "done"
    assert timeline.index("completion") < timeline.index("turn.output")


async def test_segment_close_diagnostics_do_not_replace_recorded_answer(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    timeline: list[str] = []

    class ClosingSegment(WorkspaceSegment):
        async def close(self) -> None:
            timeline.append("close")
            raise ContextContractError("close failed")

    class Provider:
        async def open(self, info: TurnInfo) -> ClosingSegment:
            return ClosingSegment(workspace)

    context = ContextEngineBuilder(system_text="sys").build()
    context.register_segment(
        replace(workspace_segment_registration(workspace), provider=Provider())
    )
    recorder = _CompletionRecorder([], timeline)
    observations = _RecordingObservations([], timeline)
    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        preparation_pipeline=TurnPreparationPipeline(()),
        completion_to_output=lambda _completion: TurnOutput(
            text="done", result_id="answer"
        ),
        completion_pipeline=TurnCompletionPipeline((recorder,)),
        observations=observations,
    )
    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())
    assert outcome.answered
    assert len(recorder.completions) == 1
    assert recorder.completions[0].context_completion.segments["workspace"] == {
        "resources": [],
    }
    assert outcome.cleanup_diagnostics == (
        CleanupDiagnostic("workspace", "ContextContractError"),
    )
    assert (
        timeline.index("completion")
        < timeline.index("close")
        < timeline.index("turn.output")
    )
    assert await context.close_segments() == ()


async def test_task_cancellation_joins_segment_close_before_releasing_the_turn(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    entered, release = asyncio.Event(), asyncio.Event()
    closed: list[str] = []

    class ClosingSegment(WorkspaceSegment):
        async def close(self) -> None:
            entered.set()
            await release.wait()
            closed.append("workspace")

    class Provider:
        async def open(self, info: TurnInfo) -> ClosingSegment:
            return ClosingSegment(workspace)

    context = ContextEngineBuilder(system_text="sys").build()
    context.register_segment(
        replace(workspace_segment_registration(workspace), provider=Provider())
    )
    recorder = _CompletionRecorder([], [])
    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        preparation_pipeline=TurnPreparationPipeline(()),
        completion_to_output=lambda _completion: TurnOutput(
            text="done", result_id="answer"
        ),
        completion_pipeline=TurnCompletionPipeline((recorder,)),
    )
    task = asyncio.create_task(
        runner.run("hello", active_day=DAY, scope=_agent_scope())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert len(recorder.completions) == 1
        with pytest.raises(ContextContractError):
            context.begin_turn("too early")
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["workspace"]
    context.begin_turn("next")
    context.abort_turn()


async def test_turn_preparation_retry_replays_only_preparation() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    preparation = _RetryTurnPreparation()
    cycles = _CountingCycleRunner()
    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, cycles),
        settings=TurnSettings(max_cycles=1),
        preparation_pipeline=TurnPreparationPipeline((preparation,)),
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert preparation.calls == 2
    assert cycles.calls == 1
    assert outcome.context_completion is not None
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.TURN


async def test_turn_completion_failure_reports_actual_failure_not_output_control() -> (
    None
):
    context = ContextEngineBuilder(system_text="sys").build()
    bus = SignalBus()
    observations = _RecordingObservations([], [])
    runner = TurnRunner(
        context=context,
        bus=bus,
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        completion_to_output=lambda _completion: TurnOutput(
            text="done",
            result_id="answer_1",
        ),
        completion_pipeline=TurnCompletionPipeline((_FailingCompletion(),)),
        observations=observations,
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.status is TurnOutcomeStatus.FAILED
    assert outcome.failure is not None
    assert outcome.failure.module == "session"
    assert outcome.failure.kind == "session.io_failed"
    assert "turn.output" not in {event.name for event in observations.events}
    failed = next(event for event in observations.events if event.name == "turn.failed")
    assert failed.level is ObservationLevel.NORMAL
    assert failed.payload["module"] == "session"


async def test_failed_finish_is_recorded_before_cleanup_diagnostics_are_reported(
    tmp_path: Path,
) -> None:
    session = SessionEngine(SessionSettings(root=tmp_path / "session"))
    session.initialize_day(DAY)
    observations = _RecordingObservations([], [])
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        completion_to_output=lambda _: TurnOutput(text="candidate", result_id="answer"),
        completion_pipeline=TurnCompletionPipeline(
            handlers=(_FailingCompletion(),),
            recorder=SessionTurnCompletionHandler(session),
        ),
        activity_controller=_FailingTurnActivity(remaining=0),
        observations=observations,
    )
    result = await runner.run("question", active_day=DAY, scope=_agent_scope())
    assert result.context_completion is not None
    ref = f"session:turn/{result.context_completion.turn_id}"
    stored = SessionStore(root=session.root).load_record(ref)
    assert isinstance(stored, SessionTurnRecord)
    assert stored.status is result.status is TurnOutcomeStatus.FAILED
    assert stored.output is None
    assert stored.finish_failures == result.finish_failures
    assert stored.failure is None  # Execution succeeded; required finish failed.
    assert result.cleanup_diagnostics[0].resource == "turn.activity"
    assert "turn.output" not in {event.name for event in observations.events}
    assert any(
        item.content.get("status") == "failed"
        for item in session.background_snapshot(DAY).items
    )


async def test_repeated_cancellation_joins_session_commit_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SessionEngine(SessionSettings(root=tmp_path / "session"))
    session.initialize_day(DAY)
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()
    original = session.record_turn
    committed: list[str] = []

    def record(*args, **kwargs) -> None:
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        original(*args, **kwargs)
        committed.append("session")

    monkeypatch.setattr(session, "record_turn", record)
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        completion_to_output=lambda _: TurnOutput(text="done", result_id="answer"),
        completion_pipeline=TurnCompletionPipeline(
            recorder=SessionTurnCompletionHandler(session)
        ),
    )
    running = asyncio.create_task(
        runner.run("question", active_day=DAY, scope=_agent_scope())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        await asyncio.sleep(0)
        assert not running.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert committed == ["session"]
    ref = session.background_snapshot(DAY).refs[0]
    output = session.inspect(f"{ref}#output")["items"]
    assert isinstance(output, list)
    assert any(isinstance(item, dict) and item.get("text") == "done" for item in output)
    assert runner.active_scope is None


async def test_session_write_failure_is_reported_without_replaying_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SessionEngine(SessionSettings(root=tmp_path / "session"))
    session.initialize_day(DAY)
    attempted: list[str] = []

    def fail_record(*args, **kwargs) -> None:
        attempted.append("record")
        raise SessionIOError("private storage details")

    monkeypatch.setattr(session, "record_turn", fail_record)
    previous = _CompletionRecorder([])
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        completion_to_output=lambda _: TurnOutput(text="candidate", result_id="answer"),
        completion_pipeline=TurnCompletionPipeline(
            handlers=(previous,),
            recorder=SessionTurnCompletionHandler(session),
        ),
    )
    result = await runner.run("question", active_day=DAY, scope=_agent_scope())
    assert result.status is TurnOutcomeStatus.FAILED
    assert len(previous.completions) == 1
    assert attempted == ["record"]
    assert result.finish_failures[0].kind == "session.io_failed"
    assert "private storage details" not in result.finish_failures[0].message
    assert session.background_snapshot(DAY).refs == ()


async def test_turn_cycle_limit_reports_exhausted_at_normal_level() -> None:
    observations = _RecordingObservations([], [])
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _EmptyCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        observations=observations,
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.status is TurnOutcomeStatus.EXHAUSTED
    exhausted = next(
        event for event in observations.events if event.name == "turn.exhausted"
    )
    assert exhausted.level is ObservationLevel.NORMAL


async def test_repeated_phase_failure_carries_accumulated_feedback_until_cycle_limit() -> (
    None
):
    observations = _RecordingObservations([], [])
    cycle_runner = _Phase1FailureCycleRunner()
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, cycle_runner),
        settings=TurnSettings(max_cycles=5),
        observations=observations,
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.status is TurnOutcomeStatus.EXHAUSTED
    assert outcome.failure is None
    assert cycle_runner.feedbacks == [
        (),
        (
            "Previous cycle phase1 failure (framework_task_failure): shared feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 1 feedback",
        ),
        (
            "Previous cycle phase1 failure (framework_task_failure): shared feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 1 feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 2 feedback",
        ),
        (
            "Previous cycle phase1 failure (framework_task_failure): shared feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 1 feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 2 feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 3 feedback",
        ),
        (
            "Previous cycle phase1 failure (framework_task_failure): shared feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 1 feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 2 feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 3 feedback",
            "Previous cycle phase1 failure (framework_task_failure): attempt 4 feedback",
        ),
    ]
    assert cycle_runner.calls == 5


async def test_turn_completion_uses_one_lifecycle_event_without_output_event() -> None:
    observations = _RecordingObservations([], [])
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _CompletionCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        completion_to_output=lambda _completion: None,
        observations=observations,
    )

    outcome = await runner.run("maintain home", active_day=DAY, scope=_agent_scope())

    assert outcome.status is TurnOutcomeStatus.COMPLETED
    completed = [
        event for event in observations.events if event.name == "turn.completed"
    ]
    assert len(completed) == 1
    assert completed[0].level is ObservationLevel.VERBOSE
    assert completed[0].payload["status"] == "completed"
    assert "turn.output" not in {event.name for event in observations.events}


async def test_turn_activity_cannot_extend_cycle_budget_and_is_cleaned() -> None:
    activity = _TurnActivity(remaining=2)
    cycles = _CountingEmptyCycleRunner()
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, cycles),
        settings=TurnSettings(max_cycles=1),
        activity_controller=activity,
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.status is TurnOutcomeStatus.EXHAUSTED
    assert cycles.calls == 1
    assert activity.cleanup_calls == 1


async def test_turn_activity_cleanup_failure_does_not_replace_turn_outcome() -> None:
    observations = _RecordingObservations([], [])
    activity = _FailingTurnActivity(remaining=0)
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _EmptyCycleRunner()),
        settings=TurnSettings(max_cycles=1),
        activity_controller=activity,
        observations=observations,
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert outcome.status is TurnOutcomeStatus.EXHAUSTED
    assert activity.cleanup_calls == 1
    assert outcome.cleanup_diagnostics == (
        CleanupDiagnostic("turn.activity", "OSError"),
    )


async def test_required_activity_failure_retains_agent_end_and_original_failure() -> (
    None
):
    from tinysoul.kernel.jobs.failures import JobError, JobFailureKind
    from tinysoul.kernel.jobs.runtime_bridge import RuntimeJobsBridge
    from tinysoul.runtime.control.exception import RUNTIME_AGENT_END

    class Activity(_TurnActivity):
        async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
            raise RuntimeJobsBridge().from_error(
                JobError(
                    "private process details",
                    kind=JobFailureKind.EXECUTION_CLOSE_FAILED,
                )
            )

    class FailedCycle:
        async def run(self, **kwargs: object) -> CycleOutcome:
            raise RuntimeException(
                reason=RUNTIME_TURN_END,
                message="Execution failed.",
                payload={"module": "test", "kind": "test.failed"},
            )

    handlers = TrapHandlerRegistry()
    handlers.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    handlers.register(RUNTIME_AGENT_END, EndFrameTrapHandler(RunLevel.AGENT))
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=RuntimeTrap(registry=handlers),
        cycle_runner=cast(CycleRunner, FailedCycle()),
        settings=TurnSettings(max_cycles=1),
        activity_controller=Activity(remaining=1),
    )
    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())
    assert outcome.status is TurnOutcomeStatus.FAILED
    assert outcome.failure is not None and outcome.failure.kind == "test.failed"
    assert (
        outcome.transfer is not None and outcome.transfer.target.level is RunLevel.AGENT
    )
    assert outcome.finish_failures[0].kind == "jobs.execution_close_failed"
    assert "private" not in repr(outcome.finish_failures)


async def test_turn_preparation_propagates_program_transfer_without_running_cycle() -> (
    None
):
    context = ContextEngineBuilder(system_text="sys").build()
    cycles = _CountingCycleRunner()
    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, cycles),
        settings=TurnSettings(max_cycles=1),
        preparation_pipeline=TurnPreparationPipeline((_EndProgramPreparation(),)),
    )

    outcome = await runner.run("hello", active_day=DAY, scope=_agent_scope())

    assert cycles.calls == 0
    assert outcome.context_completion is not None
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.AGENT
    assert outcome.status is TurnOutcomeStatus.STOPPED


def _trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(LOOP_BUDGET_REQUIRED, BudgetSuspendTrapHandler())
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    return RuntimeTrap(registry=registry)


async def test_budget_suspend_preserves_next_cycle_and_ignores_progress_as_grant() -> (
    None
):
    inbox = TurnInbox()
    context = ContextEngineBuilder(system_text="sys").build()
    seen: list[int] = []

    class Cycles:
        async def run(self, *, cycle_index: int, **kwargs: object) -> CycleOutcome:
            seen.append(cycle_index)
            return CycleOutcome(
                cycle_id=str(cycle_index),
                completion={"kind": "complete"} if cycle_index == 2 else None,
            )

    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, Cycles()),
        settings=TurnSettings(max_cycles=1),
    )
    task = asyncio.create_task(
        runner.run("question", active_day=DAY, scope=_agent_scope(), inbox=inbox)
    )
    async with asyncio.timeout(3):
        while inbox.wait_reason is not WaitReason.BUDGET:
            await asyncio.sleep(0)
        request = inbox.budget_request
        assert request is not None and request.next_cycle_index == 2
        await inbox.accept(
            InboxRecord(InboxKind.INPUT, {"text": "additional"}, "input")
        )
        await asyncio.sleep(0)
        assert seen == [1] and not task.done() and context.turn_active
        assert await inbox.grant_cycles(request.request_id, 1)
        assert not await inbox.grant_cycles(request.request_id, 1)
        result = await task
    assert seen == [1, 2]
    assert result.status is TurnOutcomeStatus.COMPLETED
    assert result.context_completion is not None
    assert [item.text for item in result.context_completion.inputs] == [
        "question",
        "additional",
    ]


async def test_question_timeout_records_waiting_terminal_without_user_answer() -> None:
    inbox = TurnInbox()
    context = ContextEngineBuilder(system_text="sys").build()

    class Cycles:
        async def run(self, **kwargs: object) -> CycleOutcome:
            return CycleOutcome(
                cycle_id="1",
                question=QuestionRequest("q", "choose", timeout_seconds=0.001),
            )

    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, Cycles()),
        settings=TurnSettings(max_cycles=1),
    )
    result = await runner.run(
        "question", active_day=DAY, scope=_agent_scope(), inbox=inbox
    )
    assert result.status is TurnOutcomeStatus.AWAITING_USER
    assert result.output is None and not context.turn_active


def _agent_scope() -> RunScope:
    return RunScope().push(RunLevel.AGENT, "program")
