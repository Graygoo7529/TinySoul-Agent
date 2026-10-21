"""LLM facilities for TinySoul."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import LLMContractError, LLMError, LLMInvariantError, TaskCancelled
from .execution.registry import ModelRegistry
from .protocol.adapter_types import AdapterKind
from .protocol.cache import PromptCache
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
from .protocol.reasoning import NativeReplay, NativeReplayMode, Reasoning
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
from .protocol.usage import TokenUsage

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
    "AdapterKind",
    "AdapterOptions",
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
    "LLMInvariantError",
    "LLMTaskError",
    "LLMTaskRunner",
    "Message",
    "MessagePart",
    "MessageStack",
    "ModelCapability",
    "ModelCapabilityError",
    "ModelContextOverflowPolicy",
    "ModelProviderBinding",
    "ModelRegistry",
    "ModelSpec",
    "NativeReplay",
    "NativeReplayMode",
    "PromptCache",
    "RawResponse",
    "Reasoning",
    "RequestOverrides",
    "ResponseStopReason",
    "SystemMessage",
    "TaskCall",
    "TaskCallValidator",
    "TaskCancellation",
    "TaskCancelled",
    "TaskFailure",
    "TaskFailureReason",
    "TaskFailureScope",
    "TaskProfile",
    "TaskResult",
    "TaskResultStatus",
    "TextAnswer",
    "TextPart",
    "TokenUsage",
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
