from __future__ import annotations
import asyncio
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import httpx
import pytest
from tests.support.project import create_test_project
from tinysoul.agent.composition.assembly import AgentRuntime
from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.config import ConfigEnvironment, ConfigError, reject_unknown_keys
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.services import ServiceScope
from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    HookOutcome,
)
from tinysoul.kernel.context.segments import (
    SegmentDescriptor,
    SegmentRegistration,
    SegmentSlot,
    TurnInfo,
)
from tinysoul.kernel.loop import TurnCompletion
from tinysoul.kernel.loop.interaction.events import TurnEventSubscription
from tinysoul.kernel.loop.lifecycle.preparation import TurnPreparationRequest
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginConfig,
    PluginGeneration,
    PluginProfileExtension,
    PluginServiceExport,
    PluginTurnResource,
    ProfileBuildContext,
    ProfileKind,
    Service,
    TurnResourceStage,
)
from tinysoul.llm.protocol.messages import Message, UserMessage
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RunScope, RuntimeException, Signal
from tinysoul.runtime.events import EnvironmentEvent, EventFilter
from tinysoul.runtime.failures import runtime_exception


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@dataclass(frozen=True)
class _ProbeSettings:
    value: int = 1


class _ProbeFailure(StrEnum):
    CONFIGURATION = "probe.configuration_failed"


def _probe_config_failure(error: ConfigError) -> RuntimeException:
    return runtime_exception(
        module="probe",
        kind=_ProbeFailure.CONFIGURATION,
        reason=RUNTIME_STARTUP_FAILED,
        message="Probe configuration is invalid.",
        payload={"key": error.key, "error_type": type(error).__name__},
    )


def _parse_probe_settings(tree: Mapping[str, object], root: Path) -> _ProbeSettings:
    del root
    reject_unknown_keys(tree, {"value"}, key="capabilities.probe")
    value = tree.get("value", 1)
    if type(value) is not int:
        raise ConfigError(
            "Probe value must be an integer", key="capabilities.probe.value"
        )
    return _ProbeSettings(value)


class _ProbeService:
    def __init__(
        self, owner: _ProbeOwner, scope: ServiceScope = ServiceScope()
    ) -> None:
        self.read = scope.local(owner.read)


class _ProbeOwner:
    def __init__(self, value: int) -> None:
        self.value = value
        self.actions: list[str] = []
        self.events: list[int] = []
        self.lifecycle: list[str] = []
        self.closed = 0

    def read(self) -> int:
        return self.value

    async def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        self.lifecycle.append("prepare")
        return ()

    async def handle(self, completion: TurnCompletion) -> None:
        self.lifecycle.append("complete")


class _ProbeResource:
    def __init__(self, owner: _ProbeOwner, stage: TurnResourceStage) -> None:
        self._owner, self._stage = owner, stage

    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        self._owner.lifecycle.append(self._stage.name.lower())
        return ()


class _ProbeUpdate:
    pass


class _ProbeSegment:
    def __init__(self, owner: _ProbeOwner) -> None:
        self._owner = owner
        self._value = owner.value

    async def prepare(self, updates: tuple[_ProbeUpdate, ...]) -> int:
        return self._owner.value if updates else self._value

    def install(self, prepared: int) -> None:
        self._value = prepared

    def seal(self) -> JsonObject:
        return {"value": self._value}

    def render(self) -> tuple[Message, ...]:
        return (UserMessage.from_json(self.seal(), label="probe"),)

    async def close(self) -> None:
        self._value = 0


class _ProbeProvider:
    def __init__(self, owner: _ProbeOwner) -> None:
        self._owner = owner

    async def open(self, info: TurnInfo) -> _ProbeSegment:
        return _ProbeSegment(self._owner)


class _ProbeHook:
    def __init__(self, owner: _ProbeOwner) -> None:
        self._owner = owner

    def check(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> HookOutcome:
        del context
        self._owner.actions.append(execution.call.action_name)
        return HookOutcome.success()


class _ProbePlugin:
    model_uses = ()
    search_capabilities = ()
    id = "probe"
    provides = ()
    requires = (WorkspaceService,)
    configuration = (
        PluginConfig(
            "capabilities.probe",
            _ProbeSettings,
            _parse_probe_settings,
            _probe_config_failure,
        ),
    )

    def __init__(self) -> None:
        self.owners: list[_ProbeOwner] = []

    async def build_generation(
        self, context: GenerationBuildContext
    ) -> PluginGeneration:
        context.services.get(WorkspaceService)
        owner = _ProbeOwner(context.settings.get(_ProbeSettings).value)
        self.owners.append(owner)

        def adapt(event: EnvironmentEvent, scope: RunScope) -> tuple[Signal, ...]:
            value = event.payload.get("value")
            if type(value) is not int:
                return ()
            owner.value = value
            owner.events.append(value)
            return (Signal("context.probe", source="probe", scope=scope, payload={}),)

        def actions(builder: ActionEngineBuilder) -> ActionEngineBuilder:
            builder.register_execution_hook("probe.answer", _ProbeHook(owner))
            builder.use_action_execution_hooks("core.answer", "probe.answer")
            return builder

        def extend(
            kind: ProfileKind, profile: ProfileBuildContext
        ) -> PluginProfileExtension | None:
            if kind is not ProfileKind.USER:
                return None
            return PluginProfileExtension(
                "probe",
                services=(Service(_ProbeService, _ProbeService(owner)),),
                segments=(
                    SegmentRegistration(
                        descriptor=SegmentDescriptor(
                            "probe_state", "probe", SegmentSlot.WORKING, 90
                        ),
                        provider=_ProbeProvider(owner),
                        signal_name="context.probe",
                        update_type=_ProbeUpdate,
                        decode=lambda signal: _ProbeUpdate(),
                    ),
                ),
                actions=actions,
                preparation=(owner,),
                completion=(owner,),
                turn_resources=tuple(
                    PluginTurnResource(_ProbeResource(owner, stage), stage)
                    for stage in (
                        TurnResourceStage.SYNCHRONIZE,
                        TurnResourceStage.RELEASE,
                    )
                ),
                events=(
                    TurnEventSubscription(
                        EventFilter(topic="probe.changed", source="host"),
                        adapt,
                        coalesce=True,
                    ),
                ),
            )

        async def close() -> None:
            owner.closed += 1

        return PluginGeneration(
            self.id,
            profile_extension_factory=extend,
            sdk_exports=(
                PluginServiceExport(
                    _ProbeService,
                    lambda scope: _ProbeService(owner, scope),
                ),
            ),
            close=close,
        )


@pytest.fixture
async def endpoint_runtimes() -> AsyncIterator[list[AgentRuntime]]:
    runtimes: list[AgentRuntime] = []
    try:
        yield runtimes
    finally:
        for runtime in reversed(runtimes):
            await runtime.close()


@dataclass
class _CompletionRecorder:
    completions: list[TurnCompletion] = field(default_factory=list)

    async def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)


async def _action_catalog_item(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    action_id: str,
) -> JsonObject:
    response = await client.get("/v2/config/actions", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    actions = payload.get("actions")
    assert isinstance(actions, list)
    for item in actions:
        if isinstance(item, dict) and item.get("id") == action_id:
            return to_json_object(item)
    raise AssertionError(f"Missing Action catalog entry: {action_id}")


def _json_object(value: object) -> JsonObject:
    assert isinstance(value, dict)
    return to_json_object(value)


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
    create_test_project(project_root)
    home_root = tmp_path / "home"
    agent_path = home_root / "agent" / "AGENT.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text("# Test Agent\n", encoding="utf-8")
    values: dict[str, object] = {
        "agent.interactive": False,
        "home.root": str(home_root),
        "home.runtime_root": str(tmp_path / "runtime" / "home"),
        "memory.root": str(tmp_path / "memory"),
        "session.root": str(tmp_path / "runtime" / "session"),
        "workspace.root": str(tmp_path / "runtime" / "workspace"),
        "reflection.archive_root": str(tmp_path / "archive"),
    }
    if overrides is not None:
        values.update(overrides)
    return ConfigEnvironment.from_project_root(
        root=project_root, env={}, overrides=values
    )


async def _run_once(app: AgentRuntime, text: str) -> TurnOutcome:
    """Exercise the real queue/Inbox path without starting mounted HTTP hosts."""
    from tinysoul.agent import UserTurnRequest

    await app.agent_runner.prepare()
    await app.generation_handle.snapshot().generation.sources.start(
        app.commands.publish_internal
    )
    handle = await app.commands.submit_turn(UserTurnRequest(text))
    running = asyncio.create_task(app.agent_runner.run())
    try:
        result = await asyncio.wait_for(handle.wait(), 10)
        assert isinstance(result.outcome, TurnOutcome)
        return result.outcome
    finally:
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        await app.agent_runner.close_requests()
        await app.close()
