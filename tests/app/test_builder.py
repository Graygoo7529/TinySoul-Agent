from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pypdf import PdfWriter

from tinysoul.app import AppSettings, ProjectInitializer, TinySoulAppBuilder
from tinysoul.endpoint import EndpointSettings
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import (
    LoopControlKind,
    LoopSettings,
    TurnSettings,
    TurnCompletion,
    build_control_request_signal,
)
from tinysoul.runtime import (
    ObservationLevel,
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


def test_app_test_config_isolates_all_mutable_roots(tmp_path: Path) -> None:
    config = _test_config(tmp_path)

    home = config.section_tree("home")
    memory = config.section_tree("memory")
    session = config.section_tree("session")
    workspace = config.section_tree("workspace")
    maintenance = config.section_tree("maintenance")

    assert home["root"] == str(tmp_path / "home")
    assert home["runtime_root"] == str(tmp_path / "runtime" / "home")
    assert memory["root"] == str(tmp_path / "memory")
    assert session["root"] == str(tmp_path / "runtime" / "session")
    assert workspace["root"] == str(tmp_path / "runtime" / "workspace")
    assert maintenance["archive_root"] == str(tmp_path / "archive")
    assert maintenance["runtime_root"] == str(tmp_path / "runtime" / "maintenance")


def test_app_builder_cleans_project_capability_staging_on_startup(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "runtime" / ".staging" / "web-interrupted" / "source.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    config = _test_config(
        tmp_path,
        overrides={
            "capabilities.resource.convert_with_markitdown.enabled": False,
            "capabilities.resource.convert_with_pypdf.enabled": False,
            "capabilities.web.search_by_kimi.enabled": False,
            "capabilities.web.discover_pages.enabled": False,
            "capabilities.web.fetch_with_defuddle.enabled": False,
            "capabilities.web.fetch_with_trafilatura.enabled": False,
        },
    )

    (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    staging = tmp_path / "runtime" / ".staging"
    assert staging.is_dir()
    assert tuple(staging.iterdir()) == ()


def test_app_builder_mounts_endpoint_as_service_and_model_output_source(
    tmp_path: Path,
) -> None:
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=True))
        .with_llm_runner(FakeLLM(()))
        .with_endpoint(EndpointSettings(token="x" * 32))
        .build()
    )

    assert app.endpoint is not None
    assert app.input_sources == ()
    assert len(app.services) == 1
    assert app.observations.mode.value == "model"


def test_agent_workspace_mutation_reaches_endpoint_event_stream(
    tmp_path: Path,
) -> None:
    note = tmp_path / "runtime" / "workspace" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("old text", encoding="utf-8")
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_endpoint(EndpointSettings(token="x" * 32))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_workspace",
                            name="select_action_domains",
                            arguments={"domains": ["workspace"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="patch_note",
                            name="workspace.patch",
                            arguments={
                                "target_link": "workspace:note.md",
                                "old_text": "old text",
                                "new_text": "new text",
                            },
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="select_core",
                            name="select_action_domains",
                            arguments={"domains": ["core"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="answer",
                            name="core.answer",
                            arguments={"guide_blocks": [{"text": "done"}]},
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _json_result({"text": "done"}),
                )
            )
        )
        .build()
    )

    outcome = app.run_once("update the note")

    assert outcome.answered is True
    assert note.read_text(encoding="utf-8") == "new text"
    assert app.endpoint is not None
    page = app.endpoint.replay_events(
        after=0,
        mode=ObservationLevel.NORMAL,
        limit=200,
    )
    changes = [
        event
        for event in page.events
        if event.name == "workspace.changed"
        and event.payload["operation"] == "patch"
    ]
    assert len(changes) == 1
    assert changes[0].source == "workspace.engine"
    assert changes[0].payload["links"] == ["workspace:note.md"]


def test_app_builder_run_once_answers_with_real_action_and_context(
    tmp_path: Path,
) -> None:
    recorder = _CompletionRecorder()
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_user_turn_completion_handler(recorder)
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
    assert outcome.context_completion is not None
    assert len(outcome.context_completion.trace.entries) == 2
    assert outcome.context_completion.inputs[0].text == "please answer"
    assert len(recorder.completions) == 1
    assert recorder.completions[0].output is not None
    assert recorder.completions[0].output.text == "done"


def test_app_builder_runs_resource_conversion_through_real_action_chain(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "runtime" / "workspace"
    source = workspace_root / "incoming" / "blank.pdf"
    source.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_llm_runner(
            FakeLLM(
                (
                    _tool_result(
                        ToolCallRecord(
                            id="select_workspace",
                            name="select_action_domains",
                            arguments={"domains": ["workspace"]},
                            kind=ToolKind.CONTROL,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="convert_1",
                            name="workspace.convert_with_pypdf",
                            arguments={
                                "source_link": "workspace:incoming/blank.pdf",
                                "target_link": "workspace:converted/blank.md",
                            },
                            kind=ToolKind.ACTION,
                        )
                    ),
                    _tool_result(
                        ToolCallRecord(
                            id="select_core",
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
                    _json_result({"text": "converted"}),
                )
            )
        )
        .build()
    )

    outcome = app.run_once("convert the PDF")

    assert outcome.answered is True
    markdown = workspace_root / "converted" / "blank.md"
    page = workspace_root / "converted" / "blank.assets" / "page-001.png"
    assert markdown.is_file()
    assert "workspace:converted/blank.assets/page-001.png" in markdown.read_text(
        encoding="utf-8"
    )
    assert page.is_file()


def test_app_builder_cycle_limit_returns_exhausted_turn(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "doc.md").write_text("hello", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=1)))
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
    assert outcome.context_completion is not None


def test_program_runner_idle_exit_ends_program(tmp_path: Path) -> None:
    app = (
        TinySoulAppBuilder(root=tmp_path)
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
        TinySoulAppBuilder(root=tmp_path)
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
    assert outcome.context_completion is not None
    assert len(llm.calls) == 3


def test_app_builder_missing_agent_is_context_startup_failure(tmp_path: Path) -> None:
    config = _test_config(
        tmp_path,
        {"home.root": str(tmp_path / "missing_home")},
    )

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
            TinySoulAppBuilder(root=tmp_path)
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
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    exc = raised.value
    assert exc.reason == RUNTIME_STARTUP_FAILED
    assert exc.payload["module"] == "workspace"
    assert exc.payload["key"] == "workspace.max_files"


def test_app_builder_script_config_error_is_script_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path, {"capabilities.script.max_source_chars": 0})

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
    assert exc.payload["module"] == "script"
    assert exc.payload["kind"] == "script.configuration_failed"
    assert exc.payload["key"] == "capabilities.script.max_source_chars"


def test_app_builder_script_dependency_error_is_script_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(
        tmp_path,
        {
            "capabilities.script.enabled": True,
            "capabilities.script.bash.enabled": True,
            "capabilities.script.bash.executable": "tinysoul-missing-bash-for-test",
        },
    )

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
    assert exc.payload["module"] == "script"
    assert exc.payload["kind"] == "script.configuration_failed"
    assert exc.payload["key"] == "capabilities.dependencies.script.bash"


def test_app_builder_supervised_process_config_error_keeps_shared_owner(
    tmp_path: Path,
) -> None:
    config = _test_config(
        tmp_path,
        {"capabilities.supervised_process.max_runtime_seconds": 0},
    )

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
    assert exc.payload["module"] == "supervised_process"
    assert exc.payload["kind"] == "supervised_process.configuration_failed"
    assert exc.payload["key"] == "capabilities.supervised_process.max_runtime_seconds"


def test_app_builder_shell_dependency_error_is_shell_startup_failure(
    tmp_path: Path,
) -> None:
    config = _test_config(
        tmp_path,
        {
            "capabilities.shell.enabled": True,
            "capabilities.shell.powershell.enabled": False,
            "capabilities.shell.cmd.enabled": True,
            "capabilities.shell.cmd.executable": "tinysoul-missing-cmd-for-test",
            "capabilities.shell.bash.enabled": False,
        },
    )

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
    assert exc.payload["module"] == "shell"
    assert exc.payload["kind"] == "shell.configuration_failed"
    assert exc.payload["key"] == "capabilities.dependencies.shell.cmd"


def test_app_builder_corrupt_manifest_is_workspace_startup_failure(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    manifest_path = workspace_root / ".tinysoul" / "workspace_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("not-json", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
            .with_config_environment(config)
            .with_app_settings(AppSettings(interactive=False))
            .with_llm_runner(FakeLLM(()))
            .build()
        )

    assert raised.value.reason == RUNTIME_STARTUP_FAILED
    assert raised.value.payload["module"] == "workspace"


def test_app_builder_does_not_map_programming_errors_to_startup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
    )

    def explode(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr(builder, "_build_workspace", explode)

    with pytest.raises(RuntimeError, match="programming error"):
        builder.build()


def test_app_builder_loop_config_error_is_loop_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"loop.max_cycles_per_turn": 0})

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
    assert exc.payload["module"] == "loop"
    assert exc.payload["key"] == "loop.max_cycles_per_turn"


def test_app_builder_app_config_error_is_app_startup_failure(tmp_path: Path) -> None:
    config = _test_config(tmp_path, {"app.interactive": "bad"})

    with pytest.raises(RuntimeException) as raised:
        (
            TinySoulAppBuilder(root=tmp_path)
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
            TinySoulAppBuilder(root=tmp_path)
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
    project_root = tmp_path / ".config-project"
    ProjectInitializer().initialize(project_root)
    home_root = tmp_path / "home"
    agent_path = home_root / "agent" / "AGENT.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text("# Test Agent\n", encoding="utf-8")
    values: dict[str, object] = {
        "app.interactive": False,
        "home.root": str(home_root),
        "home.runtime_root": str(tmp_path / "runtime" / "home"),
        "memory.root": str(tmp_path / "memory"),
        "session.root": str(tmp_path / "runtime" / "session"),
        "workspace.root": str(tmp_path / "runtime" / "workspace"),
        "maintenance.archive_root": str(tmp_path / "archive"),
        "maintenance.runtime_root": str(tmp_path / "runtime" / "maintenance"),
    }
    if overrides is not None:
        values.update(overrides)
    return ConfigEnvironment.from_project_root(root=project_root, overrides=values)
