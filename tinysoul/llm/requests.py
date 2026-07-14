"""LLM request models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.runtime import RunScope

from .cache import PromptCache
from .errors import LLMContractError
from .messages import MessageStack
from .models import ModelCapability
from .responses import AnswerFormat
from .tools import ToolScope, ToolUse


class TaskProfile(StrEnum):
    """Built-in LLM task profiles."""

    FRAMEWORK = "framework"
    LLM_ACTION = "llm_action"
    HOME_SEARCH = "home_search"
    HOME_MAINTENANCE = "home_maintenance"
    MEMORY_MAINTENANCE = "memory_maintenance"


@dataclass(frozen=True)
class CallSettings:
    """Common settings for a model call."""

    answer_format: AnswerFormat | None = None
    tool_use: ToolUse | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    required_capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.answer_format is not None and not isinstance(
            self.answer_format, AnswerFormat
        ):
            raise LLMContractError(
                "CallSettings.answer_format must be AnswerFormat or None"
            )
        if self.tool_use is not None and not isinstance(self.tool_use, ToolUse):
            raise LLMContractError("CallSettings.tool_use must be ToolUse or None")
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
        ):
            raise LLMContractError("CallSettings.temperature must be a number or None")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise LLMContractError(
                "CallSettings.max_output_tokens must be a positive integer or None"
            )
        try:
            capabilities = frozenset(self.required_capabilities)
        except TypeError as exc:
            raise LLMContractError(
                "CallSettings.required_capabilities must be an iterable"
            ) from exc
        for capability in capabilities:
            if not isinstance(capability, ModelCapability):
                raise LLMContractError(
                    "CallSettings.required_capabilities must contain ModelCapability values"
                )
        object.__setattr__(self, "required_capabilities", capabilities)

    def override_with(self, other: "CallSettings") -> "CallSettings":
        return CallSettings(
            answer_format=other.answer_format
            if other.answer_format is not None
            else self.answer_format,
            tool_use=other.tool_use
            if other.tool_use is not None
            else self.tool_use,
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
    tool_scope: ToolScope = field(default_factory=ToolScope)
    prompt_cache: PromptCache | None = None
    settings: CallSettings = field(default_factory=CallSettings)
    scope: RunScope = field(default_factory=RunScope)

    def __post_init__(self) -> None:
        if not isinstance(self.profile, (TaskProfile, str)) or not self.profile:
            raise LLMContractError("TaskCall.profile must be non-empty")
        if not isinstance(self.messages, MessageStack):
            raise LLMContractError("TaskCall.messages must be a MessageStack")
        if not isinstance(self.tool_scope, ToolScope):
            raise LLMContractError("TaskCall.tool_scope must be a ToolScope")
        if self.prompt_cache is not None and not isinstance(
            self.prompt_cache, PromptCache
        ):
            raise LLMContractError(
                "TaskCall.prompt_cache must be PromptCache or None"
            )
        if not isinstance(self.settings, CallSettings):
            raise LLMContractError("TaskCall.settings must be CallSettings")
        if not isinstance(self.scope, RunScope):
            raise LLMContractError("TaskCall.scope must be a RunScope")
