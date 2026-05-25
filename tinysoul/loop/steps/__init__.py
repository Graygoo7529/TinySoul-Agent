"""
Query Loop Tasks using the LLM Task infrastructure.

Each task encapsulates one step of the Agent Query Loop as a self-contained
AITask with its own PromptBuilder configuration and Interpreter.
"""

from .choose import ChooseActionTask
from .execute import TakeActionTask
from .update import UpdateStateTask

__all__ = [
    "ChooseActionTask",
    "TakeActionTask",
    "UpdateStateTask",
]
