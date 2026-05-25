"""AI Task module for TinySoul.

Provides unified infrastructure for AI prompt construction, execution,
and output interpretation across the query loop and workspace actions.
"""

from tinysoul.context.protocols import ContextProvider

from .interpreter import Interpreter
from .multimodal import Attachment, ContentBuilder
from .prompt import Example, InputSpec, LLMPrompt, OutputConstraint, PromptBuilder
from .result import TaskResult
from .task import AITask

__all__ = [
    "ContextProvider",
    "LLMPrompt",
    "InputSpec",
    "OutputConstraint",
    "Example",
    "PromptBuilder",
    "Attachment",
    "ContentBuilder",
    "Interpreter",
    "AITask",
    "TaskResult",
]
