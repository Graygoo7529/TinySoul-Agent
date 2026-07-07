from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigEnvironment
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import RawResponse, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import (
    LoopControlKind,
    LoopSettings,
    TinySoulAppBuilder,
    build_control_request_signal,
)
from tinysoul.runtime import (
    RUNTIME_STARTUP_FAILED,
    RunLevel,
    RuntimeException,
    RuntimeTransferAction,
    SignalBus,
)


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


def test_app_builder_run_once_answers_with_real_action_and_context() -> None:
    app = (
        TinySoulAppBuilder()
        .with_settings(LoopSettings(interactive=False, max_cycles_per_turn=2))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_1",
                            name="select_action_domains",
                            arguments={"domains": ["core"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="answer_1",
                            name="core.answer",
                            arguments={"text": "done"},
                            kind=ToolKind.ACTION,
                        )
                    ),
                )
            )
        )
        .build()
    )

    outcome = app.run_once("please answer")

    assert outcome.answered is True
    assert outcome.summary is not None
    assert outcome.summary.trace_digest["entry_count"] == 3


def test_app_builder_cycle_limit_returns_exhausted_turn() -> None:
    app = (
        TinySoulAppBuilder()
        .with_settings(LoopSettings(interactive=False, max_cycles_per_turn=1))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_1",
                            name="select_action_domains",
                            arguments={"domains": ["workspace"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="scan_1",
                            name="workspace.scan",
                            arguments={},
                            kind=ToolKind.ACTION,
                        )
                    ),
                )
            )
        )
        .build()
    )

    outcome = app.run_once("scan only")

    assert outcome.answered is False
    assert outcome.exhausted is True
    assert outcome.summary is not None


def test_program_runner_idle_exit_ends_program() -> None:
    app = (
        TinySoulAppBuilder()
        .with_settings(LoopSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    app.submit_input("exit")
    outcome = app.run()

    assert outcome.turns == ()
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def test_turn_runner_stop_control_ends_turn_without_llm_call() -> None:
    bus = SignalBus()
    llm = FakeLLM(())
    app = (
        TinySoulAppBuilder()
        .with_settings(LoopSettings(interactive=False))
        .with_signal_bus(bus)
        .with_llm_runner(llm)
        .build()
    )
    bus.emit(
        build_control_request_signal(
            LoopControlKind.STOP_TURN,
            scope=app.program_runner.scope,
            source="test",
            text="stop",
        )
    )

    outcome = app.run_once("please stop")

    assert outcome.answered is False
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.TURN
    assert outcome.summary is not None
    assert llm.calls == []


def test_app_builder_missing_agent_is_context_startup_failure(tmp_path: Path) -> None:
    config = ConfigEnvironment.from_project_root(
        root=Path.cwd(),
        overrides={"loop.interactive": False},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_settings(LoopSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "context"
    assert exc.payload["path"] == str(tmp_path / "AGENT.md")


def _tool_result(*tool_calls: ToolCallRecord) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
            tool_calls=tool_calls,
        ),
        answer=None,
        tool_calls=tool_calls,
    )
