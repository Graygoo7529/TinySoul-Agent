"""OpenAI SDK shaped provider adapter package."""

from .adapters import OpenAICompatibleChatAdapter, OpenAIResponsesAdapter
from .behavior import OpenAIAdapterBehavior, provider_reasoning_keep
from .clients import OpenAIChatCompletionsClient, OpenAIResponsesClient

__all__ = [
    "OpenAIAdapterBehavior",
    "OpenAIChatCompletionsClient",
    "OpenAICompatibleChatAdapter",
    "OpenAIResponsesAdapter",
    "OpenAIResponsesClient",
    "provider_reasoning_keep",
]
