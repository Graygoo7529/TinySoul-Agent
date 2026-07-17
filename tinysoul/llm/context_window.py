"""Model context-window usage estimation and pressure semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object

from .errors import LLMContractError, LLMError
from .messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    JsonPart,
    MessageStack,
    TextPart,
    ToolResultMessage,
)
from .models import ModelSpec
from .tools import ToolScope


@dataclass(frozen=True)
class RequestTokenEstimate:
    """Conservative provider-neutral input estimate for one request."""

    message_tokens: int
    non_message_tokens: int
    message_chars: int

    def __post_init__(self) -> None:
        for name, value in (
            ("message_tokens", self.message_tokens),
            ("non_message_tokens", self.non_message_tokens),
            ("message_chars", self.message_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LLMContractError(f"RequestTokenEstimate.{name} cannot be negative")

    @property
    def input_tokens(self) -> int:
        return self.message_tokens + self.non_message_tokens


@dataclass(frozen=True)
class ModelContextUsage:
    """Resolved hard-water usage for one candidate model attempt."""

    model_id: str
    context_window_tokens: int
    trigger_ratio: float
    estimate: RequestTokenEstimate
    reserved_output_tokens: int
    provider_reported_limit: bool = False

    @property
    def used_tokens(self) -> int:
        return self.estimate.input_tokens + self.reserved_output_tokens

    @property
    def trigger_tokens(self) -> int:
        return int(self.context_window_tokens * self.trigger_ratio)

    @property
    def over_trigger(self) -> bool:
        return self.provider_reported_limit or self.used_tokens > self.trigger_tokens

    def to_payload(self) -> JsonObject:
        return to_json_object(
            {
                "model_id": self.model_id,
                "context_window_tokens": self.context_window_tokens,
                "compression_trigger_ratio": self.trigger_ratio,
                "estimated_message_tokens": self.estimate.message_tokens,
                "estimated_non_message_tokens": self.estimate.non_message_tokens,
                "estimated_input_tokens": self.estimate.input_tokens,
                "estimated_message_chars": self.estimate.message_chars,
                "reserved_output_tokens": self.reserved_output_tokens,
                "used_tokens": self.used_tokens,
                "trigger_tokens": self.trigger_tokens,
                "provider_reported_limit": self.provider_reported_limit,
            }
        )


class ModelContextPressureError(LLMError):
    """Raised before or after a provider reports model context pressure."""

    def __init__(self, usage: ModelContextUsage) -> None:
        super().__init__(
            f"Model '{usage.model_id}' context usage {usage.used_tokens} exceeds "
            f"the hard-water limit {usage.trigger_tokens}"
        )
        self.usage = usage


class RequestTokenEstimator(Protocol):
    """Estimate one provider-neutral request before adapter invocation."""

    def estimate(
        self,
        messages: MessageStack,
        tool_scope: ToolScope,
    ) -> RequestTokenEstimate: ...


class ConservativeRequestTokenEstimator:
    """Use serialized UTF-8 bytes as a deterministic token upper estimate."""

    _MESSAGE_OVERHEAD = 16
    _PART_OVERHEAD = 4
    _TOOL_OVERHEAD = 32
    _REQUEST_OVERHEAD = 16

    def estimate(
        self,
        messages: MessageStack,
        tool_scope: ToolScope,
    ) -> RequestTokenEstimate:
        message_tokens = 0
        message_chars = 0
        for message in messages.messages:
            message_tokens += self._MESSAGE_OVERHEAD
            for part in message.parts:
                message_tokens += self._PART_OVERHEAD
                if isinstance(part, TextPart):
                    chars, tokens = _text_size(part.text)
                elif isinstance(part, JsonPart):
                    chars, tokens = _text_size(dumps_json(part.value))
                elif isinstance(part, ImagePart):
                    chars, tokens = 0, ((len(part.data) + 2) // 3) * 4
                elif isinstance(part, ImageUrlPart):
                    chars, tokens = _text_size(part.url)
                else:  # pragma: no cover - MessagePart is a closed union.
                    continue
                message_chars += chars
                message_tokens += tokens
            if isinstance(message, AssistantMessage):
                for call in message.tool_calls:
                    values = [call.id, call.name, dumps_json(call.arguments)]
                    if call.kind is not None:
                        values.append(call.kind.value)
                    for value in values:
                        chars, tokens = _text_size(value)
                        message_chars += chars
                        message_tokens += tokens
                reasoning = message.reasoning
                if reasoning is not None:
                    for value in (reasoning.content, reasoning.summary):
                        if value is None:
                            continue
                        chars, tokens = _text_size(value)
                        message_chars += chars
                        message_tokens += tokens
                    for item in reasoning.encrypted_items:
                        chars, tokens = _text_size(dumps_json(item))
                        message_chars += chars
                        message_tokens += tokens
            elif isinstance(message, ToolResultMessage):
                for value in (message.call_id, message.tool_name, message.status.value):
                    chars, tokens = _text_size(value)
                    message_chars += chars
                    message_tokens += tokens

        non_message_tokens = self._REQUEST_OVERHEAD
        for tool in tool_scope.visible_tools():
            non_message_tokens += self._TOOL_OVERHEAD
            values = [
                tool.name,
                tool.description,
                dumps_json(tool.parameters),
                tool.kind.value,
            ]
            if tool.strict is not None:
                values.append("true" if tool.strict else "false")
            non_message_tokens += sum(_text_size(value)[1] for value in values)
        selection = tool_scope.selection
        non_message_tokens += sum(
            _text_size(value)[1] for value in selection.allowed_names
        )
        if selection.forced_name is not None:
            non_message_tokens += _text_size(selection.forced_name)[1]
        return RequestTokenEstimate(
            message_tokens=message_tokens,
            non_message_tokens=non_message_tokens,
            message_chars=message_chars,
        )


class ModelContextPolicy:
    """Apply the configured hard-water ratio to candidate model requests."""

    def __init__(
        self,
        *,
        trigger_ratio: float,
        estimator: RequestTokenEstimator | None = None,
    ) -> None:
        if (
            isinstance(trigger_ratio, bool)
            or not isinstance(trigger_ratio, (int, float))
            or not 0 < trigger_ratio < 1
        ):
            raise LLMContractError(
                "Model context trigger ratio must be between 0 and 1"
            )
        self._trigger_ratio = float(trigger_ratio)
        self._estimator = estimator or ConservativeRequestTokenEstimator()

    def usage(
        self,
        *,
        model: ModelSpec,
        messages: MessageStack,
        tool_scope: ToolScope,
        reserved_output_tokens: int,
        provider_reported_limit: bool = False,
    ) -> ModelContextUsage:
        return ModelContextUsage(
            model_id=model.id,
            context_window_tokens=model.context_window_tokens,
            trigger_ratio=self._trigger_ratio,
            estimate=self._estimator.estimate(messages, tool_scope),
            reserved_output_tokens=reserved_output_tokens,
            provider_reported_limit=provider_reported_limit,
        )


def _text_size(value: str) -> tuple[int, int]:
    return len(value), len(value.encode("utf-8"))
