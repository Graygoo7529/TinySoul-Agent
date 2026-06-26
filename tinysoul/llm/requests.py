"""LLM request models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .cache import PromptCache
from .messages import MessageStack
from .models import ModelCapability
from .responses import ResponseContract
from .tools import ToolChoice, ToolSpec


class TaskProfile(StrEnum):
    """Built-in LLM task profiles."""

    FRAMEWORK = "framework"
    LLM_ACTION = "llm_action"


@dataclass(frozen=True)
class CallSettings:
    """Common settings for a model call."""

    response_contract: ResponseContract | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    required_capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)

    def override_with(self, other: "CallSettings") -> "CallSettings":
        return CallSettings(
            response_contract=other.response_contract
            if other.response_contract is not None
            else self.response_contract,
            temperature=other.temperature
            if other.temperature is not None
            else self.temperature,
            max_output_tokens=other.max_output_tokens
            if other.max_output_tokens is not None
            else self.max_output_tokens,
            required_capabilities=self.required_capabilities
            | other.required_capabilities,
        )

@dataclass(frozen=True)
class TaskCall:
    """A provider-neutral LLM task call."""

    profile: TaskProfile | str
    messages: MessageStack
    tools: tuple[ToolSpec, ...] = field(default_factory=tuple)
    tool_choice: ToolChoice | None = None
    prompt_cache: PromptCache | None = None
    settings: CallSettings = field(default_factory=CallSettings)
