"""Provider adapter base models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from tinysoul.llm.cache import PromptCache
from tinysoul.llm.adapter_types import AdapterKind, ProviderApiStyle
from tinysoul.llm.errors import LLMContractError
from tinysoul.llm.messages import MessageStack
from tinysoul.llm.models import ModelSpec
from tinysoul.llm.models import ModelProviderBinding
from tinysoul.llm.responses import AnswerFormat, RawResponse
from tinysoul.llm.tools import ToolScope, ToolUse


class ProviderErrorKind(StrEnum):
    """Provider error category used by retry and switching logic."""

    TRANSIENT = "transient"
    AUTH = "auth"
    CONFIG = "config"
    CAPABILITY = "capability"
    CONTEXT_LIMIT = "context_limit"
    PARSE = "parse"
    UNKNOWN = "unknown"


class ProviderFailureScope(StrEnum):
    """Scope that can potentially recover from a provider failure."""

    PROVIDER = "provider"
    MODEL = "model"


class ProviderError(Exception):
    """Error raised by provider adapters."""

    def __init__(
        self,
        message: str,
        *,
        kind: ProviderErrorKind,
        scope: ProviderFailureScope | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.scope = scope or (
            ProviderFailureScope.MODEL
            if kind in {ProviderErrorKind.CONFIG, ProviderErrorKind.CAPABILITY}
            else ProviderFailureScope.PROVIDER
        )


@dataclass(frozen=True)
class ProviderRequest:
    """A provider-neutral request ready for adapter mapping."""

    model: ModelSpec
    binding: ModelProviderBinding
    messages: MessageStack
    answer_format: AnswerFormat
    tool_use: ToolUse = ToolUse.DISABLED
    tool_scope: ToolScope = field(default_factory=ToolScope)
    prompt_cache: PromptCache | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, ModelSpec):
            raise LLMContractError("ProviderRequest.model must be a ModelSpec")
        if not isinstance(self.binding, ModelProviderBinding):
            raise LLMContractError(
                "ProviderRequest.binding must be a ModelProviderBinding"
            )
        if self.binding not in self.model.providers:
            raise LLMContractError(
                "ProviderRequest.binding must belong to ProviderRequest.model"
            )
        if not isinstance(self.messages, MessageStack):
            raise LLMContractError("ProviderRequest.messages must be a MessageStack")
        if not isinstance(self.answer_format, AnswerFormat):
            raise LLMContractError(
                "ProviderRequest.answer_format must be an AnswerFormat"
            )
        if not isinstance(self.tool_use, ToolUse):
            raise LLMContractError("ProviderRequest.tool_use must be a ToolUse")
        if not isinstance(self.tool_scope, ToolScope):
            raise LLMContractError("ProviderRequest.tool_scope must be a ToolScope")
        if self.prompt_cache is not None and not isinstance(
            self.prompt_cache, PromptCache
        ):
            raise LLMContractError(
                "ProviderRequest.prompt_cache must be PromptCache or None"
            )
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
        ):
            raise LLMContractError(
                "ProviderRequest.temperature must be a number or None"
            )
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise LLMContractError(
                "ProviderRequest.max_output_tokens must be a positive integer or None"
            )
        if self.timeout_seconds is not None and (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise LLMContractError(
                "ProviderRequest.timeout_seconds must be a positive number or None"
            )
class ProviderAdapter(Protocol):
    """Provider adapter protocol."""

    provider_id: str
    adapter_kind: AdapterKind

    @property
    def api_style(self) -> ProviderApiStyle:
        """Wire style fixed by the adapter kind."""
        ...

    def invoke(self, request: ProviderRequest) -> RawResponse:
        """Invoke a model through this provider."""
        ...
