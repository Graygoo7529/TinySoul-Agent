"""Cross-module context pressure recovery tests."""

from __future__ import annotations

from datetime import date as CalendarDate

from datetime import date
from tinysoul.plugins.workspace.projection import workspace_segment_registration

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tinysoul.kernel.context import (
    ContextEngineBuilder,
    ContextSignalBatch,
    build_trace_phase_note_signal,
)
from tinysoul.kernel.context.prompts import PromptBlock, TaskPrompt
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.llm.protocol.adapter import adapter_spec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ProviderApiStyle
from tinysoul.llm.protocol.routing import ModelChain, TaskSpec
from tinysoul.llm.execution.model_chain import TaskSpecTable
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.provider import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.protocol.requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
)
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    RawResponse,
    TaskResult,
    TaskResultStatus,
)
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.llm.protocol.tools import ToolUse
from tinysoul.agent.user.runtime import build_user_turn_trap
from tinysoul.plugins.reflection.turn.runtime import build_reflection_turn_trap
from tinysoul.kernel.loop.pressure import PressureRecoveryStatus, required_chars
from tinysoul.agent.user.pressure import UserContextPressureRecovery
from tinysoul.plugins.reflection.turn import ReflectionContextPressureRecovery
from tinysoul.runtime import (
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeModuleRunner,
    RuntimeTransferAction,
    RuntimeTransferInterrupt,
    SignalBus,
)
from tinysoul.plugins.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceSettings,
)


@dataclass
class _CapacityProvider:
    provider_id: str = "capacity"
    adapter_kind: AdapterKind = AdapterKind.OPENAI_COMPATIBLE_CHAT
    requests: list[ProviderRequest] = field(default_factory=list)

    async def close(self) -> None:
        pass

    @property
    def api_style(self) -> ProviderApiStyle:
        return adapter_spec(self.adapter_kind).api_style

    async def invoke(self, request: ProviderRequest) -> RawResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise ProviderError(
                "private provider detail", kind=ProviderErrorKind.CONTEXT_LIMIT
            )
        return RawResponse(
            answer_text='{"ok": true}',
            model_id=request.model.id,
            provider_id=self.provider_id,
        )


@pytest.mark.parametrize("reflection", [False, True], ids=["user", "reflection"])
@pytest.mark.parametrize("reclaimable", [False, True], ids=["no_progress", "recompose"])
async def test_capacity_recovery_rebuilds_task_or_ends_without_replaying_completed_work(
    tmp_path: Path,
    reflection: bool,
    reclaimable: bool,
) -> None:
    context = (
        ContextEngineBuilder(system_text="system")
        .with_trace_heap(chunk_max_chars=12000, branch_factor=4, min_hot_entries=0)
        .build()
    )
    turn_id = context.begin_turn("continue")
    await context.open_segments(CalendarDate(2026, 7, 12))
    scope = (
        _scope(turn_id)
        .push(RunLevel.CYCLE, "next")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    bus = SignalBus()
    if reclaimable:
        for index in range(3):
            bus.emit(
                build_trace_phase_note_signal(
                    {"detail": "x" * 1000},
                    scope=scope,
                    source="test",
                    cycle_id=f"previous_{index}",
                    phase=CyclePhase.PHASE3,
                )
            )
        await context.consume_signals(bus)
    canonical = context.seal_trace()
    workspace = _workspace(tmp_path / "workspace")
    (tmp_path / "home").mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    from tinysoul.kernel.registration import PluginRegistry
    plugins = PluginRegistry(()).resolve(context)
    trap = (
        build_reflection_turn_trap(context, plugins=plugins)
        if reflection
        else build_user_turn_trap(context=context, plugins=plugins)
    )
    modules = RuntimeModuleRunner(trap=trap, bus=bus)
    writes: list[str] = []

    def write_resource(module_scope: RunScope) -> None:
        writes.append("committed")
        workspace.write_text("workspace:committed.txt", "committed")

    (await modules.run(scope=scope, name="workspace.write", callback=write_resource))
    provider = _CapacityProvider()
    runner = LLMTaskRunner(
        models=ModelRegistry(
            [
                ModelSpec(
                    id="model",
                    providers=(ModelProviderBinding(provider.provider_id, "model"),),
                    context_window_tokens=262144,
                    adapter=provider.adapter_kind,
                    capabilities=frozenset(
                        {
                            ModelCapability.TEXT_INPUT,
                            ModelCapability.JSON_OBJECT_OUTPUT,
                        }
                    ),
                ),
            ]
        ),
        providers=ProviderRegistry([provider]),
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    profile="test",
                    chain=ModelChain(profile="test", model_ids=("model",)),
                    settings=CallSettings(
                        answer_format=AnswerFormat.JSON_OBJECT,
                        tool_use=ToolUse.DISABLED,
                    ),
                ),
            ]
        ),
    )

    async def invoke(module_scope: RunScope) -> TaskResult:
        return await runner.run(
            TaskCall(
                profile="test",
                messages=context.compose(
                    TaskPrompt(
                        guide_blocks=(
                            PromptBlock.from_text("task", "Reply with JSON."),
                        )
                    )
                ),
                scope=module_scope,
                context_overflow_policy=ModelContextOverflowPolicy.REQUEST_RECOVERY,
            )
        )

    if reclaimable:
        result = await modules.run(scope=scope, name="llm.task", callback=invoke)
        assert result.status is TaskResultStatus.SUCCESS
        assert len(provider.requests) == 2
        assert provider.requests[0].messages != provider.requests[1].messages
    else:
        with pytest.raises(RuntimeTransferInterrupt) as raised:
            (await modules.run(scope=scope, name="llm.task", callback=invoke))
        assert raised.value.transfer.action is RuntimeTransferAction.END
        assert raised.value.transfer.target == scope.nearest(RunLevel.TURN)
        assert len(provider.requests) == 1
    assert writes == ["committed"]
    assert (tmp_path / "workspace" / "committed.txt").read_text(
        encoding="utf-8"
    ) == "committed"
    assert context.seal_trace() == canonical


def test_model_pressure_converts_target_token_gap_to_char_reclaim() -> None:
    required = required_chars(
        {
            "context_window_tokens": 100,
            "estimated_message_tokens": 70,
            "estimated_non_message_tokens": 10,
            "reserved_output_tokens": 10,
            "estimated_message_chars": 700,
        },
        target_ratio=0.5,
    )

    assert required == 400


async def test_image_only_pressure_does_not_delete_workspace_files(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.write_text(
        "workspace:temporary.txt",
        "temporary",
    )
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("continue")
    await context.open_segments(CalendarDate(2026, 7, 12))
    scope = _scope(turn_id)

    result = UserContextPressureRecovery(
        context=context,
        target_ratio=0.8,
    ).recover(
        payload={
            "estimated_chars": 50,
            "estimated_image_bytes": 20,
            "max_image_bytes": 10,
        },
        scope=scope,
    )

    assert result.status is PressureRecoveryStatus.NO_PROGRESS
    assert (tmp_path / "temporary.txt").is_file()


async def test_reflection_pressure_never_reclaims_active_workspace(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.write_text(
        "workspace:active.txt",
        "active work",
    )
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("maintain memory")
    await context.open_segments(CalendarDate(2026, 7, 12))

    ReflectionContextPressureRecovery(context).recover(
        payload={"estimated_chars": 1000, "max_chars": 100},
        scope=_scope(turn_id),
    )

    assert {record.link for record in workspace.snapshot().resources} == {
        "workspace:active.txt"
    }


def _workspace(tmp_path: Path):
    return WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()


def _scope(turn_id: str) -> RunScope:
    return RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, turn_id)
