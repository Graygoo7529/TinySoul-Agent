"""LLM request models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .cache import PromptCache
from .messages import MessageStack
from .responses import ResponseContract


class TaskProfile(StrEnum):
    """Built-in LLM task profiles."""

    FRAMEWORK = "framework"
    LLM_ACTION = "llm_action"


@dataclass(frozen=True)
class CallSettings:
    """Common settings for a model call."""

    temperature: float | None = None
    max_output_tokens: int | None = None

    def override_with(self, other: "CallSettings") -> "CallSettings":
        return CallSettings(
            temperature=other.temperature
            if other.temperature is not None
            else self.temperature,
            max_output_tokens=other.max_output_tokens
            if other.max_output_tokens is not None
            else self.max_output_tokens,
        )


@dataclass(frozen=True)
class TaskCallOverrides:
    """Optional per-call overrides for task configuration."""

    response_contract: ResponseContract | None = None
    settings: CallSettings = field(default_factory=CallSettings)


@dataclass(frozen=True)
class TaskCall:
    """A provider-neutral LLM task call."""

    profile: TaskProfile | str
    messages: MessageStack
    prompt_cache: PromptCache | None = None
    overrides: TaskCallOverrides = field(default_factory=TaskCallOverrides)
