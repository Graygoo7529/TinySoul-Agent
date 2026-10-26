"""Opt-in model capability checks through real adapters and remote SDK requests."""

from __future__ import annotations

import asyncio
import json
import os
import re
import struct
import zlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import httpx2
import pytest

from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.network import resolve_project_network
from tinysoul.infra.settings import parse_infra_settings
from tinysoul.llm.adapter import ProviderAdapter, ProviderError, ProviderRequest
from tinysoul.llm.adapter.catalog import adapter_spec
from tinysoul.llm.adapter.factory import build_provider_registry
from tinysoul.llm.config.loader import LLMConfigParser, ProviderSpec
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImagePart,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.protocol.reasoning import NativeReplayMode
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    JsonAnswer,
    RawResponse,
    ResponseInterpreter,
    ResponseStopReason,
)
from tinysoul.llm.protocol.tools import ToolKind, ToolScope, ToolSpec, ToolUse

pytestmark = pytest.mark.external


def _environment() -> ConfigEnvironment:
    root = os.environ.get("TINYSOUL_REAL_PROJECT_ROOT", "").strip()
    if not root:
        pytest.fail("TINYSOUL_REAL_PROJECT_ROOT must name a configured project")
    return ConfigEnvironment.from_project_root(Path(root).expanduser().resolve())


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "model_id" not in metafunc.fixturenames:
        return
    if (
        metafunc.config.getoption("suite") != "external"
        or os.environ.get("TINYSOUL_RUN_REAL_LLM_API") != "1"
    ):
        metafunc.parametrize(
            "model_id",
            [
                pytest.param(
                    "disabled", marks=pytest.mark.skip(reason="real API disabled")
                )
            ],
        )
        return
    config = LLMConfigParser().parse(_environment().section_tree("llm"))
    selected = tuple(
        dict.fromkeys(
            item.strip()
            for item in os.environ.get("TINYSOUL_REAL_MODELS", "").split(",")
            if item.strip()
        )
    )
    unknown = set(selected) - set(config.models.ids())
    if unknown:
        raise pytest.UsageError(f"Unknown real API model IDs: {sorted(unknown)}")
    provider_id = os.environ.get("TINYSOUL_REAL_PROVIDER", "").strip()
    if provider_id and provider_id not in {item.id for item in config.providers}:
        raise pytest.UsageError(f"Unknown real API provider: {provider_id}")
    metafunc.parametrize("model_id", selected or config.models.ids())


@dataclass
class RequestCapture:
    """Observe serialized JSON bodies without retaining credentials or replacing I/O."""

    bodies: list[JsonObject] = field(default_factory=list, repr=False)
    connections: list[dict[str, str]] = field(default_factory=list)

    def record(self, method: str, content_type: str, content: bytes) -> None:
        if method == "POST" and "application/json" in content_type:
            self.bodies.append(to_json_object(json.loads(content)))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Any is confined to the two SDK transports' public send kwargs.
        send = httpx.AsyncClient.send
        send2 = httpx2.AsyncClient.send

        async def observe(
            client: httpx.AsyncClient, request: httpx.Request, **kwargs: Any
        ) -> httpx.Response:
            self.record(
                request.method, request.headers.get("content-type", ""), request.content
            )
            response = await send(client, request, **kwargs)
            self.connections.append(
                {
                    "url": str(request.url),
                    **{
                        name: request.headers[name]
                        for name in ("user-agent", "x-opencode-session")
                        if name in request.headers
                    },
                }
            )
            return response

        async def observe2(
            client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: Any
        ) -> httpx2.Response:
            self.record(
                request.method, request.headers.get("content-type", ""), request.content
            )
            response = await send2(client, request, **kwargs)
            self.connections.append(
                {
                    "url": str(request.url),
                    **{
                        name: request.headers[name]
                        for name in ("user-agent", "x-opencode-session")
                        if name in request.headers
                    },
                }
            )
            return response

        monkeypatch.setattr(httpx.AsyncClient, "send", observe)
        monkeypatch.setattr(httpx2.AsyncClient, "send", observe2)


@dataclass(frozen=True)
class RealModel:
    model: ModelSpec
    binding: ModelProviderBinding
    adapter: ProviderAdapter
    capture: RequestCapture
    cache_key: str = field(default_factory=lambda: f"real-api:{uuid4().hex}")

    def require(self, capability: ModelCapability) -> None:
        if not self.model.supports(capability):
            pytest.skip(f"{self.model.id} does not declare {capability.value}")

    def request(self, messages: MessageStack) -> ProviderRequest:
        return ProviderRequest(
            model=self.model,
            binding=self.binding,
            messages=messages,
            answer_format=AnswerFormat.TEXT,
            max_output_tokens=8192,
            timeout_seconds=120,
            prompt_cache=PromptCache(key=self.cache_key),
        )

    async def invoke(self, request: ProviderRequest, step: str) -> RawResponse:
        count = len(self.capture.bodies)
        try:
            async with asyncio.timeout(150):
                response = await self.adapter.invoke(request)
        except ProviderError as exc:
            # Remote failures must not become successful/skipped checks.
            pytest.fail(
                f"{self.model.id}/{self.binding.provider_id} {step}: "
                f"{exc.kind.value} ({exc.scope.value}): {exc}; cause={type(exc.__cause__).__name__}",
                pytrace=False,
            )
        assert len(self.capture.bodies) > count, "No real SDK JSON request observed"
        connection = self.capture.connections[-1]
        assert connection["user-agent"].startswith("TinySoul-Agent")
        if self.binding.provider_id == "opencode":
            assert request.prompt_cache is not None
            assert connection["x-opencode-session"] == request.prompt_cache.key
        assert response.stop_reason in {
            ResponseStopReason.COMPLETE,
            ResponseStopReason.TOOL_CALLS,
        }, f"{step}: incomplete response ({response.stop_reason.value})"
        native = response.reasoning.native_replay if response.reasoning else None
        print(
            "[real-llm] "
            + json.dumps(
                {
                    "model": self.model.id,
                    "provider": self.binding.provider_id,
                    "step": step,
                    "connection": connection,
                    "stop": response.stop_reason.value,
                    "replay_mode": native.mode.value if native else None,
                    "replay_values": len(_replay_values(native.ordered_items))
                    if native
                    else 0,
                    "usage": response.usage.to_json(),
                }
            )
        )
        return response


@pytest.fixture
async def real_model(
    model_id: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[RealModel]:
    environment = _environment()
    config = LLMConfigParser().parse(environment.section_tree("llm"))
    model = config.models.get(model_id)
    selected_provider = os.environ.get("TINYSOUL_REAL_PROVIDER", "").strip()
    provider: ProviderSpec | None = None
    binding: ModelProviderBinding | None = None
    for candidate in model.providers:
        current = config.provider(candidate.provider_id)
        if selected_provider:
            if current.id != selected_provider:
                continue
        elif not current.enabled:
            continue
        if current.configured_api_key(environment.runtime_env):
            provider, binding = replace(current, enabled=True), candidate
            break
    if provider is None or binding is None:
        pytest.skip(
            f"{model_id}: no credentialed binding for "
            f"{selected_provider or 'enabled providers'}"
        )
    key_env = next(
        name
        for name in provider.api_key_envs
        if environment.runtime_env.get(name, "").strip()
    )
    print(
        "[real-llm] "
        + json.dumps(
            {
                "model": model.id,
                "provider": provider.id,
                "provider_model": binding.provider_model,
                "api_mode": adapter_spec(model.adapter).api_mode.value,
                "key_env": key_env,
            }
        )
    )
    capture = RequestCapture()
    capture.install(monkeypatch)
    registry = await build_provider_registry(
        (provider,),
        models=ModelRegistry([model]),
        env=environment.runtime_env,
        network=resolve_project_network(
            environment.parse_section("infra", parse_infra_settings).network,
            environment,
        ),
    )
    try:
        yield RealModel(
            model, binding, registry.get(provider.id, model.adapter), capture
        )
    finally:
        await registry.close()


def _json_answer(response: RawResponse) -> JsonObject:
    result = ResponseInterpreter().interpret(
        response, AnswerFormat.JSON_OBJECT, ToolUse.DISABLED
    )
    assert isinstance(result.answer, JsonAnswer)
    return result.answer.value


def _assistant(response: RawResponse) -> AssistantMessage:
    return AssistantMessage.from_text(
        response.answer_text,
        reasoning=response.reasoning,
        tool_calls=response.tool_calls,
    )


def _objects(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _objects(child)


def _replay_values(value: object) -> set[tuple[str, str]]:
    """Compare opaque values in memory; never print them in diagnostics."""
    values: set[tuple[str, str]] = set()
    for item in _objects(value):
        for key in (
            "reasoning_content",
            "encrypted_content",
            "signature",
            "thought_signature",
            "thoughtSignature",
        ):
            content = item.get(key)
            if isinstance(content, str) and content:
                values.add(
                    (key.replace("thought_signature", "thoughtSignature"), content)
                )
        if item.get("type") in {"thinking", "redacted_thinking"}:
            for key in ("thinking", "data"):
                content = item.get(key)
                if isinstance(content, str) and content:
                    values.add((key, content))
    return values


async def test_real_model_json(real_model: RealModel) -> None:
    real_model.require(ModelCapability.JSON_OBJECT_OUTPUT)
    request = replace(
        real_model.request(
            MessageStack.of(
                SystemMessage.from_text("Return only a JSON object without markdown."),
                UserMessage.from_text(
                    'Compute 137*249+89*61. Put the integer under "value".'
                ),
            )
        ),
        answer_format=AnswerFormat.JSON_OBJECT,
    )
    response = await real_model.invoke(request, "json")
    assert _json_answer(response).get("value") == 39542


async def test_real_model_image(real_model: RealModel) -> None:
    real_model.require(ModelCapability.IMAGE_INPUT)
    request = real_model.request(
        MessageStack.of(
            UserMessage.from_parts(
                TextPart(
                    "Identify the dominant color in the image. Return only a JSON object "
                    'with key "color". Choose exactly one basic color: red, green, blue, '
                    "yellow, black, white. Do not add shade adjectives."
                ),
                ImagePart(data=_sample_png(), mime_type="image/png"),
            ),
        )
    )
    response = await real_model.invoke(request, "image")
    assert any(
        item.get("type") in {"image", "image_url", "input_image"}
        or "inlineData" in item
        or "inline_data" in item
        for item in _objects(real_model.capture.bodies[-1])
    ), "The SDK request did not contain the image"
    assert str(_json_answer(response).get("color", "")).lower() == "red"


async def test_real_model_tools(real_model: RealModel) -> None:
    real_model.require(ModelCapability.TOOL_CALLING)
    tool = ToolSpec(
        name="lookup_record",
        description="Look up a synthetic record by its id.",
        parameters={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        kind=ToolKind.ACTION,
    )
    request = replace(
        real_model.request(
            MessageStack.of(
                SystemMessage.from_text(
                    "Use lookup_record when asked. After its result arrives, return only a JSON "
                    'object with its value under "value". Do not invent tool results.'
                ),
                UserMessage.from_text("Call lookup_record with id alpha."),
            )
        ),
        tool_use=ToolUse.OPTIONAL,
        tool_scope=ToolScope(tools=(tool,)),
    )
    first = await real_model.invoke(request, "tool")
    assert len(first.tool_calls) == 1
    call = first.tool_calls[0]
    assert call.name == "lookup_record" and call.arguments == {"id": "alpha"}
    messages = request.messages.append(_assistant(first)).append(
        ToolResultMessage.from_json(
            call_id=call.id, tool_name=call.name, value={"id": "alpha", "value": 42}
        )
    )
    second = await real_model.invoke(replace(request, messages=messages), "tool-result")
    assert _json_answer(second).get("value") == 42


async def test_real_model_reasoning_replay(real_model: RealModel) -> None:
    model = real_model.model
    mode = model.adapter_options.native_replay_mode()
    # K3's adapter always replays content even without an explicit option.
    if mode is NativeReplayMode.NONE and not (
        model.adapter is AdapterKind.KIMI and model.adapter_options.variant == "k3"
    ):
        pytest.skip("Native replay is not configured for this model")
    request = real_model.request(
        MessageStack.of(
            SystemMessage.from_text(
                "Think carefully. Return only a JSON object without markdown."
            ),
            UserMessage.from_text(
                'Compute 137*249+89*61. Put the integer under "value".'
            ),
        )
    )
    first = await real_model.invoke(request, "reasoning-first")
    assert _json_answer(first).get("value") == 39542
    replay = first.reasoning.native_replay if first.reasoning else None
    assert replay is not None, "No native reasoning state returned"
    values = _replay_values(replay.ordered_items)
    assert values, "NativeReplay has no non-empty replay content/signature"
    messages = request.messages.append(_assistant(first)).append(
        UserMessage.from_text(
            'Multiply that result by 13. Return the new integer under "value".'
        )
    )
    second = await real_model.invoke(
        replace(request, messages=messages), "reasoning-replay"
    )
    sent = _replay_values(real_model.capture.bodies[-1])
    if not values.issubset(sent):
        pytest.fail(
            "Retained native state was not sent in the continuation", pytrace=False
        )
    assert _json_answer(second).get("value") == 514046


async def test_real_model_prompt_cache(real_model: RealModel) -> None:
    # Implicit caches may work without a configurable prompt_cache capability.
    identity = uuid4().hex
    codes = [100000 + uuid4().int % 900000 for _ in range(600)]
    prefix = (
        f"Synthetic cache audit {identity}. Look up the requested record's code.\n"
        + "\n".join(
            f"Record {index:04d}: reference code {code}; this synthetic library item is available."
            for index, code in enumerate(codes)
        )
    )
    cache = PromptCache(
        key=f"real-api:{identity}",
        breakpoints=(
            PromptCacheBreakpoint("background", 0),
            PromptCacheBreakpoint("trace", 1),
        ),
    )
    request = replace(
        real_model.request(
            MessageStack.of(
                SystemMessage.from_text(prefix),
                UserMessage.from_text(
                    "Find the reference code of record 0121. Reply with that code."
                ),
            )
        ),
        prompt_cache=cache,
    )
    first = await real_model.invoke(request, "cache-first")
    assert re.search(rf"\b{codes[121]}\b", first.answer_text), (
        "Cached prefix was not used"
    )
    first_body = real_model.capture.bodies[-1]
    messages = request.messages.append(_assistant(first)).append(
        UserMessage.from_text(
            "Now find the reference code of record 0459. Reply with that code."
        )
    )
    second = await real_model.invoke(replace(request, messages=messages), "cache-reuse")
    assert re.search(rf"\b{codes[459]}\b", second.answer_text), (
        "Cached prefix was not reused"
    )
    second_body = real_model.capture.bodies[-1]
    if "prompt_cache_key" in first_body:
        assert (
            first_body["prompt_cache_key"]
            == second_body.get("prompt_cache_key")
            == cache.key
        )
    mode = real_model.model.adapter_options.values.get("prompt_cache_mode")
    if adapter_spec(
        real_model.model.adapter
    ).api_mode is ApiMode.ANTHROPIC_MESSAGES and mode in {"explicit", "automatic"}:
        assert any("cache_control" in item for item in _objects(first_body))
        assert (first.usage.cache_creation_input_tokens or 0) > 0, (
            "No explicit cache creation reported"
        )
    assert second.usage.cached_input_tokens is not None, (
        "Remote usage does not report cache reads; cache hit remains unverified"
    )
    # A provider can already report hits for its own fixed prefix on the first
    # call. The unique synthetic prefix must add hits beyond that baseline.
    assert second.usage.cached_input_tokens > (first.usage.cached_input_tokens or 0), (
        "Repeated long prefix did not increase cache hits beyond the first-call baseline"
    )


def _sample_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = (b"\x00" + b"\xff\x00\x00" * 64) * 64
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )
