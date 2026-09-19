"""LLM facilities for TinySoul."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protocol.cache import PromptCache
from .protocol.adapter_types import AdapterKind
from .errors import LLMContractError, LLMError, LLMInvariantError, TaskCancelled
from .protocol.messages import (
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
from .protocol.models import (
    AdapterOptions,
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
    RequestOverrides,
)
from .execution.registry import ModelRegistry
from .protocol.reasoning import Reasoning, ReasoningKeep
from .protocol.requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
    TaskCancellation,
    TaskProfile,
)
from .protocol.responses import (
    Answer,
    AnswerFormat,
    JsonAnswer,
    RawResponse,
    ResponseStopReason,
    TaskFailure,
    TaskFailureReason,
    TaskFailureScope,
    TaskResult,
    TaskResultStatus,
    TextAnswer,
)
from .protocol.tools import (
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
    from .execution.task import (
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
    "ModelContextOverflowPolicy",
    "TaskCallValidator",
}

__all__ = [
    "Answer",
    "AnswerFormat",
    "AdapterOptions",
    "AdapterKind",
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
    "LLMInvariantError",
    "LLMTaskError",
    "LLMTaskRunner",
    "Message",
    "MessagePart",
    "MessageStack",
    "ModelCapability",
    "ModelCapabilityError",
    "ModelRegistry",
    "ModelProviderBinding",
    "ModelSpec",
    "PromptCache",
    "RequestOverrides",
    "RawResponse",
    "ResponseStopReason",
    "Reasoning",
    "ReasoningKeep",
    "SystemMessage",
    "TaskCall",
    "TaskCancellation",
    "TaskCallValidator",
    "TaskFailure",
    "TaskFailureReason",
    "TaskFailureScope",
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
        from .execution import task

        return getattr(task, name)
    raise AttributeError(f"module 'tinysoul.llm' has no attribute {name!r}")
