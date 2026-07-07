"""LLM facilities for TinySoul."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cache import PromptCache
from .errors import LLMContractError, LLMError, LLMInvariantError
from .failures import LLMFailureKind
from .messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    JsonPart,
    Message,
    MessagePart,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from .models import (
    ModelCapability,
    ModelRegistry,
    ModelSpec,
    ProviderOptions,
    ProviderRequestOverrides,
)
from .reasoning import Reasoning, ReasoningKeep
from .requests import CallSettings, TaskCall, TaskProfile
from .responses import (
    Answer,
    AnswerFormat,
    JsonAnswer,
    RawResponse,
    TaskFailure,
    TaskResult,
    TaskResultStatus,
    TextAnswer,
)
from .tools import (
    DefaultToolCallIdMapper,
    ToolCallIdMapper,
    ToolCallRecord,
    ToolKind,
    ToolResultStatus,
    ToolScope,
    ToolSelection,
    ToolSpec,
    ToolUse,
)

if TYPE_CHECKING:
    from .task import (
        CapabilityPolicy,
        CurrentModelCapabilities,
        LLMTaskError,
        LLMTaskRunner,
        ModelCapabilityError,
        TaskCallValidator,
    )

_TASK_EXPORTS = {
    "CapabilityPolicy",
    "CurrentModelCapabilities",
    "LLMTaskError",
    "LLMTaskRunner",
    "ModelCapabilityError",
    "TaskCallValidator",
}

__all__ = [
    "Answer",
    "AnswerFormat",
    "AssistantMessage",
    "CallSettings",
    "CapabilityPolicy",
    "CurrentModelCapabilities",
    "DefaultToolCallIdMapper",
    "ImagePart",
    "ImageUrlPart",
    "JsonAnswer",
    "JsonPart",
    "LLMContractError",
    "LLMError",
    "LLMFailureKind",
    "LLMInvariantError",
    "LLMTaskError",
    "LLMTaskRunner",
    "Message",
    "MessagePart",
    "MessageStack",
    "ModelCapability",
    "ModelCapabilityError",
    "ModelRegistry",
    "ModelSpec",
    "PromptCache",
    "ProviderOptions",
    "ProviderRequestOverrides",
    "RawResponse",
    "Reasoning",
    "ReasoningKeep",
    "SystemMessage",
    "TaskCall",
    "TaskCallValidator",
    "TaskFailure",
    "TaskProfile",
    "TaskResult",
    "TaskResultStatus",
    "TextAnswer",
    "TextPart",
    "ToolCallIdMapper",
    "ToolCallRecord",
    "ToolKind",
    "ToolResultMessage",
    "ToolResultStatus",
    "ToolScope",
    "ToolSelection",
    "ToolSpec",
    "ToolUse",
    "UserMessage",
]


def __getattr__(name: str) -> object:
    if name in _TASK_EXPORTS:
        from . import task

        return getattr(task, name)
    raise AttributeError(f"module 'tinysoul.llm' has no attribute {name!r}")
