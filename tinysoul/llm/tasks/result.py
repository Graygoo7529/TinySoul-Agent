"""AI Task result structure for TinySoul.

TaskResult unifies the Interpreter-parsed JSON dict with the raw AIResponse
metadata (reasoning_content, usage, model name, etc.) in a single return value.
"""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.llm.provider.response import AIResponse


@dataclass
class TaskResult:
    """Result of an AITask.run() execution.

    Attributes:
        data:      The Interpreter-parsed JSON dict (e.g. {"action_name": "..."})
        response:  The raw AIResponse with content, reasoning_content, metadata, etc.
    """

    data: dict
    response: AIResponse
