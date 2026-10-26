from __future__ import annotations
from dataclasses import dataclass, field
from tinysoul.infra.json import JsonObject
from tinysoul.llm.execution.context_window import RequestTokenEstimate
from tinysoul.llm.protocol.messages import MessageStack
from tinysoul.llm.execution.model_chain import Clock, TaskSpecTable
from tinysoul.llm.protocol.routing import ModelChain, TaskSpec
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.adapter.catalog import adapter_spec
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.protocol.requests import CallSettings
from tinysoul.llm.protocol.responses import (
    JsonAnswer,
    RawResponse,
    AnswerFormat,
    TaskResult,
)
from tinysoul.runtime import ObservationEvent, ObservationLevel
from tinysoul.llm.protocol.tools import ToolKind, ToolScope, ToolSpec, ToolUse


@dataclass
class FakeProvider:
    provider_id: str
    adapter_kind: AdapterKind = AdapterKind.OPENAI_CHAT
    failures: dict[str, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    requests: list[ProviderRequest] = field(default_factory=list)

    async def close(self) -> None:
        pass

    @property
    def api_mode(self):
        return adapter_spec(self.adapter_kind).api_mode

    async def invoke(self, request: ProviderRequest) -> RawResponse:
        model_id = request.model.id
        self.calls.append(model_id)
        self.requests.append(request)
        remaining = self.failures.get(model_id, 0)
        if remaining > 0:
            self.failures[model_id] = remaining - 1
            raise ProviderError("temporary failure", kind=ProviderErrorKind.TRANSIENT)
        return RawResponse(
            answer_text='{"model": "' + model_id + '"}',
            model_id=model_id,
            provider_id=self.provider_id,
        )


@dataclass
class FakeClock(Clock):
    current: float = 0.0

    def now(self) -> float:
        return self.current


@dataclass
class RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


@dataclass
class FixedTokenEstimator:
    message_tokens: int
    non_message_tokens: int = 0
    message_chars: int = 100

    def estimate(
        self, messages: MessageStack, tool_scope: ToolScope
    ) -> RequestTokenEstimate:
        return RequestTokenEstimate(
            message_tokens=self.message_tokens,
            non_message_tokens=self.non_message_tokens,
            message_chars=self.message_chars,
        )


def _models(*ids: str) -> ModelRegistry:
    capabilities = frozenset(
        {
            ModelCapability.TEXT_INPUT,
            ModelCapability.JSON_OBJECT_OUTPUT,
        }
    )
    return ModelRegistry(
        [
            ModelSpec(
                id=model_id,
                providers=(ModelProviderBinding("fake", model_id),),
                context_window_tokens=262_144,
                adapter=AdapterKind.OPENAI_CHAT,
                capabilities=capabilities,
            )
            for model_id in ids
        ]
    )


def _window_models(*items: tuple[str, int]) -> ModelRegistry:
    capabilities = frozenset(
        {
            ModelCapability.TEXT_INPUT,
            ModelCapability.JSON_OBJECT_OUTPUT,
        }
    )
    return ModelRegistry(
        [
            ModelSpec(
                id=model_id,
                providers=(ModelProviderBinding("fake", model_id),),
                context_window_tokens=window,
                adapter=AdapterKind.OPENAI_CHAT,
                capabilities=capabilities,
            )
            for model_id, window in items
        ]
    )


def _tasks(
    chain: ModelChain,
    *,
    max_output_tokens: int | None = None,
) -> TaskSpecTable:
    return TaskSpecTable(
        [
            TaskSpec(
                profile=chain.profile,
                chain=chain,
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                    max_output_tokens=max_output_tokens,
                ),
            )
        ]
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        kind=ToolKind.ACTION,
    )


def _json_output(result: TaskResult) -> JsonObject:
    if not isinstance(result.answer, JsonAnswer):
        raise AssertionError("Expected JSON answer")
    return result.answer.value
