from __future__ import annotations

from collections import deque

from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import RawResponse, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import LoopSettings, TinySoulAppBuilder


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
