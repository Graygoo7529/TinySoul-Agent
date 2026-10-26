from __future__ import annotations
from dataclasses import dataclass
import pytest
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.adapter import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import RawResponse
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.errors import TaskCancelled
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    RuntimeException,
    RuntimeTransferInterrupt,
    RuntimeTransfer,
    RunFrame,
    RunLevel,
)
from tinysoul.llm.protocol.tools import ToolScope
from tests.llm.execution.support import (
    FakeProvider,
    _models,
    _tasks,
    _tool,
)


async def test_model_chain_exhaustion_becomes_runtime_reason() -> None:
    provider = FakeProvider(
        provider_id="fake",
        failures={"a": 2, "b": 2},
    )
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_provider=1,
                    max_cycles=1,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ProviderError"
    assert exc_info.value.payload["provider_error_kind"] == "transient"


async def test_model_chain_exhaustion_payload_reports_non_transient_provider_error() -> (
    None
):
    @dataclass
    class ConfigFailingProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            raise ProviderError(
                "bad provider config",
                kind=ProviderErrorKind.CONFIG,
                scope=ProviderFailureScope.PROVIDER,
            )

    provider = ConfigFailingProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_provider=3,
                    max_cycles=10,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ProviderError"
    assert exc_info.value.payload["provider_error_kind"] == "config"
    assert provider.calls == ["a", "b"]


@pytest.mark.parametrize(
    "control",
    (
        RuntimeException(reason=RUNTIME_TURN_END, message="Stop."),
        RuntimeTransferInterrupt(RuntimeTransfer.end(RunFrame(RunLevel.TURN, "turn"))),
        TaskCancelled("cancelled"),
    ),
    ids=("runtime_exception", "resolved_transfer", "task_cancelled"),
)
async def test_classified_control_preserves_identity_without_retry(
    control: Exception,
) -> None:
    class ControlledProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            raise control

    provider = ControlledProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a", "b"))),
    )

    with pytest.raises(type(control)) as raised:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert raised.value is control
    assert provider.calls == ["a"]


async def test_programming_error_aborts_chain_without_switching_models() -> None:
    @dataclass
    class BuggyProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            raise RuntimeError("programming error")

    provider = BuggyProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(max_retries_per_provider=3, max_cycles=10),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.payload["kind"] == LLMFailureKind.INTERNAL_FAILURE
    assert provider.calls == ["a"]


async def test_contract_failure_maps_to_runtime_turn_end() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    tool_scope=ToolScope(tools=(_tool(),)),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.CONTRACT_VIOLATION


async def test_runner_reports_unknown_model_as_contract_violation() -> None:
    runner = LLMTaskRunner(
        models=ModelRegistry([]),
        providers=ProviderRegistry([FakeProvider(provider_id="fake")]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("missing",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.CONTRACT_VIOLATION


@pytest.mark.parametrize(
    "adapter",
    [
        AdapterKind.OPENAI_CHAT,
        AdapterKind.ANTHROPIC_MESSAGES,
        AdapterKind.GOOGLE_GENERATE_CONTENT,
    ],
)
async def test_runner_reports_model_chain_exhaustion_without_routable_provider(
    adapter: AdapterKind,
) -> None:
    model = ModelSpec(
        id="model_a",
        providers=(ModelProviderBinding("missing", "model-a"),),
        context_window_tokens=262_144,
        adapter=adapter,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("model_a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED

    assert exc_info.value.payload["provider_error_kind"] == "config"
