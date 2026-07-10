from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tinysoul.app import AppSettings, TinySoulAppBuilder
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import (
    LoopControlKind,
    LoopSettings,
    TurnCompletion,
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


@dataclass
class _CompletionRecorder:
    completions: list[TurnCompletion] = field(default_factory=list)

    def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)


def test_app_builder_run_once_answers_with_real_action_and_context(
    tmp_path: Path,
) -> None:
    recorder = _CompletionRecorder()
    app = (
        TinySoulAppBuilder()
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(max_cycles_per_turn=2))
        .with_turn_completion_handler(recorder)
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
                            arguments={"guide_blocks": [{"text": "answer"}]},
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _json_result({"text": "done"}),
                )
            )
        )
        .build()
    )

    outcome = app.run_once("please answer")

    assert outcome.answered is True
    assert outcome.summary is not None
    assert outcome.summary.trace_digest["entry_count"] == 2
    assert outcome.summary.inputs[0]["text"] == "please answer"
    assert len(outcome.summary.trace) == 2
    assert len(recorder.completions) == 1
    assert recorder.completions[0].output is not None
    assert recorder.completions[0].output.text == "done"


def test_app_builder_cycle_limit_returns_exhausted_turn(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "doc.md").write_text("hello", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {
            "workspace.root": str(workspace_root),
            "workspace.manifest_path": str(
                workspace_root / ".tinysoul" / "manifest.json"
            ),
        },
    )
    app = (
        TinySoulAppBuilder()
        .with_config_environment(config)
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(max_cycles_per_turn=1))
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


def test_program_runner_idle_exit_ends_program(tmp_path: Path) -> None:
    app = (
        TinySoulAppBuilder()
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    app.submit_input("exit")
    outcome = app.run()

    assert outcome.turns == ()
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def test_turn_runner_ignores_stop_control_without_turn_scope(tmp_path: Path) -> None:
    bus = SignalBus()
    llm = FakeLLM(
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
                    arguments={"guide_blocks": [{"text": "answer"}]},
                    kind=ToolKind.ACTION,
                )
            ),
            _json_result({"text": "done"}),
        )
    )
    app = (
        TinySoulAppBuilder()
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
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

    assert outcome.answered is True
    assert outcome.transfer is None
    assert outcome.summary is not None
    assert len(llm.calls) == 3


def test_app_builder_missing_agent_is_context_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path)

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "home"


def test_app_builder_home_config_error_is_home_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"home.max_read_chars": 0})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder()
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "home"
    assert exc.payload["key"] == "home.max_read_chars"


def test_app_builder_workspace_config_error_is_workspace_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"workspace.max_files": 0})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder()
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "workspace"
    assert exc.payload["key"] == "workspace.max_files"


def test_app_builder_loop_config_error_is_loop_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"loop.max_cycles_per_turn": 0})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder()
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "loop"
    assert exc.payload["key"] == "loop.max_cycles_per_turn"


def test_app_builder_app_config_error_is_app_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"app.interactive": "bad"})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder()
            .with_config_environment(config)
            .with_loop_settings(LoopSettings())
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "app"
    assert exc.payload["key"] == "app.interactive"


def test_app_builder_llm_config_error_is_llm_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"llm.tasks.framework.models": ["missing_model"]})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder()
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_loop_settings(LoopSettings())
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "llm"
    assert exc.payload["key"] == "llm.tasks.framework.models"


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


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _test_config(
    tmp_path: Path,
    overrides: dict[str, object] | None = None,
) -> ConfigEnvironment:
    values: dict[str, object] = {
        "app.interactive": False,
        "home.runtime_root": str(tmp_path / "runtime_home"),
    }
    if overrides is not None:
        values.update(overrides)
    return ConfigEnvironment.from_project_root(root=Path.cwd(), overrides=values)
