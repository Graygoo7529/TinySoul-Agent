"""Exercise Anthropic stream completion and lifecycle through the real SDK."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import cast

import httpx2
import pytest
from anthropic import AsyncAnthropic

from tests.support.anthropic import anthropic_sse_response
from tinysoul.llm.adapter.anthropic.messages import (
    AnthropicMessagesAdapter,
    MessagesClient,
)
from tinysoul.llm.adapter.base import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from tinysoul.llm.config.types import ProviderEndpoint, ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.protocol.models import AdapterOptions, ModelProviderBinding, ModelSpec
from tinysoul.llm.protocol.responses import AnswerFormat, ResponseStopReason

pytestmark = pytest.mark.anyio


@pytest.fixture
def invocation() -> ProviderRequest:
    binding = ModelProviderBinding("test", "model-latest")
    return ProviderRequest(
        model=ModelSpec(
            id="test-latest",
            adapter=AdapterKind.ANTHROPIC_MESSAGES,
            providers=(binding,),
            context_window_tokens=100000,
        ),
        binding=binding,
        messages=MessageStack.of(UserMessage.from_text("Say OK")),
        answer_format=AnswerFormat.TEXT,
        max_output_tokens=32768,
    )


@asynccontextmanager
async def adapter_for(
    respond: Callable[[httpx2.Request], httpx2.Response],
) -> AsyncGenerator[AnthropicMessagesAdapter]:
    async with AsyncAnthropic(
        api_key="test-key",
        base_url="https://provider.test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as sdk:
        yield AnthropicMessagesAdapter(
            provider=ProviderSpec(
                id="test",
                api_key_envs=("TEST_KEY",),
                endpoints=(
                    ProviderEndpoint(
                        ApiMode.ANTHROPIC_MESSAGES, "https://provider.test"
                    ),
                ),
            ),
            messages=cast(MessagesClient, sdk.messages),
        )


def message(stop_reason: str | None = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "model-latest",
        "content": [{"type": "text", "text": "OK"}],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def event(payload: dict[str, object]) -> bytes:
    return f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n".encode()


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", ResponseStopReason.COMPLETE),
        ("max_tokens", ResponseStopReason.OUTPUT_LIMIT),
    ],
)
async def test_large_budget_without_timeout_preserves_sampling_and_stop_reason(
    invocation: ProviderRequest,
    stop_reason: str,
    expected: ResponseStopReason,
) -> None:
    requests: list[httpx2.Request] = []

    def respond(req: httpx2.Request) -> httpx2.Response:
        requests.append(req)
        return anthropic_sse_response(message(stop_reason))

    invocation = replace(
        invocation,
        temperature=0.4,
        top_p=0.8,
        model=replace(
            invocation.model,
            adapter_options=AdapterOptions(
                {"extra_body": {"metadata": {"user_id": "test-user"}}}
            ),
        ),
    )
    async with adapter_for(respond) as adapter:
        result = await adapter.invoke(invocation)
    assert result.answer_text == "OK"
    assert result.stop_reason is expected
    assert result.usage.output_tokens == 2
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["stream"] is True
    assert body["max_tokens"] == 32768
    assert body["temperature"] == 0.4
    assert body["top_p"] == 0.8
    assert body["metadata"] == {"user_id": "test-user"}


@pytest.mark.parametrize(
    ("error_type", "detail", "expected"),
    [
        ("overloaded_error", "private body", ProviderErrorKind.TRANSIENT),
        ("authentication_error", "private body", ProviderErrorKind.AUTH),
        ("invalid_request_error", "private body", ProviderErrorKind.CONFIG),
        (
            "invalid_request_error",
            "context length exceeded; private body",
            ProviderErrorKind.CONTEXT_LIMIT,
        ),
        ("new_error", "private body", ProviderErrorKind.UNKNOWN),
    ],
)
async def test_error_after_http_success_is_classified_without_retry_or_body(
    invocation: ProviderRequest,
    error_type: str,
    detail: str,
    expected: ProviderErrorKind,
) -> None:
    responses: list[httpx2.Response] = []

    def respond(req: httpx2.Request) -> httpx2.Response:
        response = httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=event(
                {"type": "error", "error": {"type": error_type, "message": detail}}
            ),
        )
        responses.append(response)
        return response

    async with adapter_for(respond) as adapter:
        with pytest.raises(ProviderError) as failure:
            await adapter.invoke(invocation)
    assert failure.value.kind is expected
    assert failure.value.scope is ProviderFailureScope.PROVIDER
    assert "private body" not in str(failure.value)
    assert len(responses) == 1
    assert responses[0].is_closed


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"", ProviderErrorKind.PARSE),
        (b"event: message_start\ndata: invalid-json\n\n", ProviderErrorKind.PARSE),
        (
            event({"type": "message_start", "message": message(None)}),
            ProviderErrorKind.TRANSIENT,
        ),
    ],
    ids=["empty", "invalid-json", "early-eof"],
)
async def test_incomplete_stream_does_not_publish_partial_response(
    invocation: ProviderRequest,
    body: bytes,
    expected: ProviderErrorKind,
) -> None:
    response = httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=body
    )
    async with adapter_for(lambda req: response) as adapter:
        with pytest.raises(ProviderError) as failure:
            await adapter.invoke(invocation)
    assert failure.value.kind is expected
    assert response.is_closed


class InterruptedStream(httpx2.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield event({"type": "message_start", "message": message(None)})
        raise httpx2.ReadError("private transport failure")

    async def aclose(self) -> None:
        self.closed = True


async def test_transport_failure_during_stream_is_transient_and_closes(
    invocation: ProviderRequest,
) -> None:
    stream = InterruptedStream()
    async with adapter_for(
        lambda req: httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )
    ) as adapter:
        with pytest.raises(ProviderError) as failure:
            await adapter.invoke(invocation)
    assert failure.value.kind is ProviderErrorKind.TRANSIENT
    assert "private transport" not in str(failure.value)
    assert stream.closed


class WaitingStream(httpx2.AsyncByteStream):
    def __init__(self) -> None:
        self.reading = asyncio.Event()
        self.closed = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield event({"type": "message_start", "message": message(None)})
        self.reading.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed.set()


async def test_cancellation_closes_stream_and_leaves_shared_client_usable(
    invocation: ProviderRequest,
) -> None:
    stream = WaitingStream()

    def respond(req: httpx2.Request) -> httpx2.Response:
        if not stream.closed.is_set():
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        return anthropic_sse_response(message())

    async with adapter_for(respond) as adapter:
        task = asyncio.create_task(adapter.invoke(invocation))
        try:
            await asyncio.wait_for(stream.reading.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stream.closed.is_set()
        assert (await adapter.invoke(invocation)).answer_text == "OK"
