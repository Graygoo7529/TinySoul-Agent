"""Provider adapter base models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from tinysoul.llm.cache import PromptCache
from tinysoul.llm.messages import MessageStack
from tinysoul.llm.models import ModelSpec
from tinysoul.llm.responses import ModelResponse, ResponseContract


class ProviderErrorKind(StrEnum):
    """Provider error category used by retry and switching logic."""

    TRANSIENT = "transient"
    AUTH = "auth"
    CONFIG = "config"
    CAPABILITY = "capability"
    PARSE = "parse"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """Error raised by provider adapters."""

    def __init__(self, message: str, *, kind: ProviderErrorKind) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ProviderRequest:
    """A provider-neutral request ready for adapter mapping."""

    model: ModelSpec
    messages: MessageStack
    response_contract: ResponseContract
    prompt_cache: PromptCache | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


class ProviderAdapter(Protocol):
    """Provider adapter protocol."""

    provider_id: str

    def invoke(self, request: ProviderRequest) -> ModelResponse:
        """Invoke a model through this provider."""
        ...
