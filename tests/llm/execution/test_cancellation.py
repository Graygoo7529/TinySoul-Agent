from __future__ import annotations
from dataclasses import dataclass
import asyncio
import pytest
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.execution.model_chain import Sleeper
from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.protocol.requests import TaskCall, TaskCancellation
from tinysoul.llm.protocol.responses import RawResponse
from tinysoul.llm.errors import TaskCancelled
from tinysoul.llm.execution.task import LLMTaskRunner
from tests.llm.execution.support import (
    FakeProvider,
    _models,
    _tasks,
)


async def test_runner_passes_action_remaining_timeout_to_provider_request() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )
    (
        await runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                cancellation=TaskCancellation(
                    cancelled=lambda: False,
                    remaining_seconds=lambda: 12.5,
                    reason=lambda: "",
                ),
            )
        )
    )

    assert provider.requests[0].timeout_seconds == pytest.approx(12.5)


async def test_runner_stops_retry_chain_after_owner_cancellation() -> None:
    state = {"cancelled": False}

    @dataclass
    class CancellingProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            state["cancelled"] = True
            raise ProviderError("temporary failure", kind=ProviderErrorKind.TRANSIENT)

    provider = CancellingProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_provider=2,
                    max_cycles=10,
                ),
            )
        ),
    )

    with pytest.raises(TaskCancelled, match="timeout"):
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    cancellation=TaskCancellation(
                        cancelled=lambda: state["cancelled"],
                        remaining_seconds=lambda: 10.0,
                        reason=lambda: "timeout",
                    ),
                )
            )
        )

    assert provider.calls == ["a"]


@pytest.mark.parametrize("max_retries", [0, 1], ids=["model_switch", "provider_retry"])
async def test_owner_cancellation_interrupts_and_joins_backoff(
    max_retries: int,
) -> None:
    sleeping, cleaned = asyncio.Event(), asyncio.Event()
    cancelled = False

    class BlockingSleeper(Sleeper):
        async def sleep(self, seconds: float) -> None:
            sleeping.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    provider = FakeProvider(provider_id="fake", failures={"a": 10})
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_provider=max_retries,
                    max_cycles=1,
                ),
            )
        ),
        sleeper=BlockingSleeper(),
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
        cancellation=TaskCancellation(
            cancelled=lambda: cancelled,
            remaining_seconds=lambda: None,
            reason=lambda: "stop",
        ),
    )
    work = asyncio.create_task(runner.run(call))
    await asyncio.wait_for(sleeping.wait(), 1)
    cancelled = True
    with pytest.raises(TaskCancelled, match="stop"):
        await asyncio.wait_for(work, 1)
    assert cleaned.is_set()
    assert provider.calls == ["a"]
    await runner.close()


async def test_repeated_task_cancellation_joins_provider_finalizer() -> None:
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Provider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
            raise AssertionError("unreachable")

    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([Provider(provider_id="fake")]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )
    task = asyncio.create_task(
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )
    )
    await started.wait()
    task.cancel()
    await cleaning.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await runner.close()
