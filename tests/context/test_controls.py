"""Tests for context control tools and normalization."""

from __future__ import annotations

from tinysoul.context import (
    CONTROL_EVICT_BACKGROUND,
    CONTROL_LOAD_BACKGROUND,
    CONTROL_UPDATE_WORKING,
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_WORKING_PATCH,
    ContextControlScopeBuilder,
    ControlCallNormalizer,
    ControlResultStage,
)
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunLevel, RunScope

SCOPE = RunScope().push(RunLevel.PHASE, "phase1")


def test_control_scope_reflects_loadable_and_loaded_links() -> None:
    builder = ContextControlScopeBuilder()
    scope = builder.build(
        loadable_links=("home:what@a",),
        loaded_links=("home:what@b",),
    )
    names = [tool.name for tool in scope.tools]
    assert names == [
        CONTROL_UPDATE_WORKING,
        CONTROL_LOAD_BACKGROUND,
        CONTROL_EVICT_BACKGROUND,
    ]
    assert all(tool.kind is ToolKind.CONTROL for tool in scope.tools)

    minimal = builder.build(loadable_links=(), loaded_links=())
    assert [tool.name for tool in minimal.tools] == [CONTROL_UPDATE_WORKING]


def test_normalize_update_working_produces_signal() -> None:
    normalizer = ControlCallNormalizer()
    normalization = normalizer.normalize(
        (
            ToolCallRecord(
                id="call_1",
                name=CONTROL_UPDATE_WORKING,
                arguments={
                    "set_milestones": [{"key": "goal", "content": "done soon"}],
                    "set_todos": [
                        {"key": "t1", "content": "write", "status": "in_progress"}
                    ],
                },
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=SCOPE,
    )
    assert normalization.results == ()
    assert len(normalization.signals) == 1
    signal = normalization.signals[0]
    assert signal.name == SIGNAL_WORKING_PATCH
    assert signal.payload["call_id"] == "call_1"


def test_normalize_background_calls_produce_signals() -> None:
    normalizer = ControlCallNormalizer()
    normalization = normalizer.normalize(
        (
            ToolCallRecord(
                id="call_1",
                name=CONTROL_LOAD_BACKGROUND,
                arguments={"links": ["home:what@a"]},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="call_2",
                name=CONTROL_EVICT_BACKGROUND,
                arguments={"links": ["home:what@b"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=SCOPE,
    )
    assert normalization.results == ()
    assert [signal.name for signal in normalization.signals] == [
        SIGNAL_BACKGROUND_PATCH,
        SIGNAL_BACKGROUND_PATCH,
    ]
    assert normalization.signals[0].payload["load_links"] == ["home:what@a"]
    assert normalization.signals[1].payload["evict_links"] == ["home:what@b"]


def test_normalize_failures_become_local_results() -> None:
    normalizer = ControlCallNormalizer()
    normalization = normalizer.normalize(
        (
            ToolCallRecord(
                id="dup",
                name=CONTROL_UPDATE_WORKING,
                arguments={"set_milestones": [{"key": "a", "content": "b"}]},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(id="dup", name=CONTROL_UPDATE_WORKING, arguments={}),
            ToolCallRecord(id="c3", name="unknown_tool", arguments={}),
            ToolCallRecord(
                id="c4",
                name=CONTROL_UPDATE_WORKING,
                arguments={},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="c5",
                name=CONTROL_UPDATE_WORKING,
                arguments={"set_todos": [{"key": "", "content": "x"}]},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="c6",
                name=CONTROL_LOAD_BACKGROUND,
                arguments={"links": []},
                kind=ToolKind.ACTION,
            ),
        ),
        scope=SCOPE,
    )
    assert len(normalization.signals) == 1
    reasons = {
        result.call_id: result.frame_data.get("reason") or result.frame_data.get("tool_kind")
        for result in normalization.results
    }
    assert reasons["dup"] == "duplicate_call_id"
    assert reasons["c3"] == "unknown_control_tool"
    assert reasons["c4"] == "empty_patch"
    assert reasons["c5"] == "invalid_arguments"
    assert reasons["c6"] == "action"
    assert all(
        result.stage is ControlResultStage.NORMALIZE for result in normalization.results
    )
