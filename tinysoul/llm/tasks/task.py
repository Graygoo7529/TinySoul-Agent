"""AI Task execution wrapper.

Encapsulates a single AI call (prompt construction + execution + interpretation)
and unifies debug output across all AI invocations in the system.

Single entry point:
- run():  Prompt → AI → TaskResult(data=dict, response=AIResponse)
"""

from __future__ import annotations

from typing import Any

from tinysoul.infra.config import settings
from tinysoul.infra import EventLogger, NullSink
from tinysoul.llm.provider import get_ai_client
from tinysoul.llm.provider.config import ChatConfig, LLMProfileName
from tinysoul.llm.provider.response import AIResponse

from .interpreter import Interpreter
from .prompt import LLMPrompt
from .result import TaskResult


class AITask:
    """A self-contained AI task: prompt construction + execution + interpretation.

    All AI calls in TinySoul (query loop steps and workspace actions)
    should flow through this class to ensure consistent debug output
    and error handling.
    """

    def __init__(
        self,
        prompt: LLMPrompt | None = None,
        interpreter: Interpreter | None = None,
        client: Any | None = None,
        logger: EventLogger | None = None,
    ):
        self.prompt = prompt
        self._interpreter = interpreter or Interpreter()
        self._client = client
        self._logger = logger or EventLogger(sinks=[NullSink()])

    def run(
        self,
        *,
        profile: LLMProfileName | str,
        system: list[dict[str, str]] | None = None,
        config: ChatConfig | None = None,
    ) -> TaskResult:
        """Execute the AI task and return a TaskResult.

        Args:
            system: Optional system messages to prepend.
            config: Optional per-request generation parameters (temperature,
                    max_tokens, timeout, etc.). Overrides the pool-level config.

        Returns:
            TaskResult with:
            - data:      Interpreter-parsed JSON dict
            - response:  Raw AIResponse (content, reasoning_content, metadata, ...)

        Used by Query Loop three-step tasks and OneStepAIExecutor.
        Attachments in LLMPrompt (e.g. images) are converted to multimodal
        message content automatically.
        """
        response = self._call(profile=profile, system=system, config=config)
        data = self._interpreter.interpret(response)
        return TaskResult(data=data, response=response)

    def _call(
        self,
        *,
        profile: LLMProfileName | str,
        system: list[dict[str, str]] | None = None,
        config: ChatConfig | None = None,
    ) -> AIResponse:
        """Execute via LLMPrompt (text + optional attachments)."""
        user_prompt = self.prompt.serialize() if self.prompt else ""

        self._logger.debug_prompt(
            system=system,
            user=user_prompt,
            source="loop_step",
        )

        # Build multimodal message from text + attachments
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        if self.prompt and self.prompt.attachments:
            for att in self.prompt.attachments:
                content_parts.append(att.to_content_part())

        messages: list[dict[str, Any]] = [{"role": "user", "content": content_parts}]

        client = self._client if self._client is not None else get_ai_client()
        response = client.chat(
            messages=messages,
            profile=profile,
            system=system,
            config=config,
        )

        self._logger.debug_prompt(
            system=system,
            user=f"[AIResponse model={response.metadata.get('model', '?')} content_len={len(response.content)}]",
            source="ai_response",
        )
        return response
