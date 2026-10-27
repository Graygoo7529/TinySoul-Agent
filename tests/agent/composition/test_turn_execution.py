from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from pypdf import PdfWriter
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.kernel.loop import (
    LoopControlKind,
    LoopSettings,
    TurnSettings,
    build_control_request_signal,
)
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    RawResponse,
    TaskFailure,
    TaskFailureReason,
    TaskFailureScope,
    TaskResult,
)
from tinysoul.plugins.session.records.store import SessionStore
from tinysoul.runtime import RunLevel, RuntimeTransferAction, SignalBus
from tests.agent.composition.support import (
    FakeLLM,
    _CompletionRecorder,
    _text_result,
    _run_once,
    _test_config,
    _tool_result,
)

pytestmark = pytest.mark.integration


def test_agent_test_config_isolates_all_mutable_roots(tmp_path: Path) -> None:
    config = _test_config(tmp_path)

    home = config.section_tree("home")
    memory = config.section_tree("memory")
    session = config.section_tree("session")
    workspace = config.section_tree("workspace")
    reflection = config.section_tree("reflection")

    assert home["root"] == str(tmp_path / "home")
    assert home["runtime_root"] == str(tmp_path / "runtime" / "home")
    assert memory["root"] == str(tmp_path / "memory")
    assert session["root"] == str(tmp_path / "runtime" / "session")
    assert workspace["root"] == str(tmp_path / "runtime" / "workspace")
    assert reflection["archive_root"] == str(tmp_path / "archive")


@pytest.mark.parametrize("fail_first", [False, True])
async def test_agent_builder_run_once_answers_with_real_action_and_context(
    tmp_path: Path, fail_first: bool,
) -> None:
    recorder = _CompletionRecorder()
    decision = (
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
    )
    failed = TaskResult.failure_result(
        raw_response=RawResponse("", "fake", "fake"),
        failure=TaskFailure(
            reason=TaskFailureReason.OUTPUT_LIMIT_REACHED,
            scope=TaskFailureScope.OUTPUT,
            model_feedback="The generation reached its output limit.",
        ),
    )
    body = "Done. See [report](workspace:report.md#summary)."
    first_attempt = (*decision, failed) if fail_first else ()
    llm = FakeLLM((*first_attempt, *decision, _text_result(body)))
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=2)))
        .with_user_turn_completion_handler(recorder)
        .with_llm_runner(llm)
        .build()
        .build_runtime()
    )

    outcome = await _run_once(app, "please answer")

    assert outcome.answered is True
    assert outcome.context_completion is not None
    assert [entry.kind.value for entry in outcome.context_completion.trace.entries] == (
        ["input"] + ["decision", "action_result"] * (2 if fail_first else 1)
    )
    assert outcome.context_completion.inputs[0].text == "please answer"
    assert len(recorder.completions) == 1
    assert recorder.completions[0].output is not None
    assert recorder.completions[0].output.text == body
    assert llm.calls[-1].settings.answer_format is AnswerFormat.TEXT
    (record,) = SessionStore(root=tmp_path / "runtime" / "session").list_records()
    assert record.output is not None
    assert record.output.text == body
    assert record.output.references == ("workspace:report.md#summary",)
    assert [action.outcome.value for action in record.actions] == (
        ["failed", "success"] if fail_first else ["success"]
    )


async def test_agent_builder_runs_resource_conversion_through_real_action_chain(
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
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
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
                                "source_ref": "workspace:incoming/blank.pdf",
                                "target_ref": "workspace:converted/blank.md",
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
                    _text_result("converted"),
                )
            )
        )
        .build()
        .build_runtime()
    )

    outcome = await _run_once(app, "convert the PDF")

    assert outcome.answered is True
    markdown = workspace_root / "converted" / "blank.md"
    page = workspace_root / "converted" / "blank.assets" / "page-001.png"
    assert markdown.is_file()
    assert "workspace:converted/blank.assets/page-001.png" in markdown.read_text(
        encoding="utf-8"
    )
    assert page.is_file()


async def test_agent_builder_cycle_limit_suspends_until_explicit_decision(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "doc.md").write_text("hello", encoding="utf-8")
    config = _test_config(
        tmp_path,
        {"workspace.root": str(workspace_root)},
    )
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(config)
        .with_agent_settings(AgentSettings(interactive=False))
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
                            name="workspace.list",
                            arguments={},
                            kind=ToolKind.ACTION,
                        )
                    ),
                )
            )
        )
        .build()
        .build_runtime()
    )

    from tinysoul.agent import UserTurnRequest
    from tinysoul.kernel.loop.interaction.inbox import WaitReason

    await app.agent_runner.prepare()
    handle = await app.commands.submit_turn(UserTurnRequest("scan only"))
    running = asyncio.create_task(app.agent_runner.run())
    try:
        async with asyncio.timeout(3):
            while handle.wait_reason is not WaitReason.BUDGET:
                assert not handle.done
                await asyncio.sleep(0.01)
        assert handle.budget_request is not None
        assert handle.budget_request.next_cycle_index == 2
        await app.commands.cancel_request(handle.request_id)
        assert (await handle.wait()).outcome is not None
    finally:
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        await app.close()


async def test_agent_runner_idle_exit_ends_program(tmp_path: Path) -> None:
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )

    await app.submit_input("exit")
    outcome = await app.run()

    assert outcome.turns == ()
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.AGENT


async def test_turn_runner_ignores_stop_control_without_turn_scope(
    tmp_path: Path,
) -> None:
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
            _text_result("done"),
        )
    )
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_signal_bus(bus)
        .with_llm_runner(llm)
        .build()
        .build_runtime()
    )
    bus.emit(
        build_control_request_signal(
            LoopControlKind.STOP_TURN,
            scope=app.agent_runner.scope,
            source="test",
            text="stop",
        )
    )

    outcome = await _run_once(app, "please stop")

    assert outcome.answered is True
    assert outcome.transfer is None
    assert outcome.context_completion is not None
    assert len(llm.calls) == 3
