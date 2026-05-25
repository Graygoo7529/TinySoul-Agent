"""Shared LLM execution utilities for action executors.

Eliminates duplication between OneStepAIExecutor, RegisterTemporaryScriptExecutor,
and any future executor that needs a single LLM call with standardized timeout
resolution.
"""

from __future__ import annotations

from typing import Any

from tinysoul.action.framework.run_config import RunConfig
from tinysoul.infra.config import settings
from tinysoul.llm.provider.config import ChatConfig, LLMProfileName
from tinysoul.llm.tasks import Interpreter, LLMPrompt
from tinysoul.llm.tasks.task import AITask


def run_llm_task(
    prompt: LLMPrompt,
    system: list[dict[str, str]] | None,
    client: Any | None,
    run_config: RunConfig | None = None,
) -> dict[str, Any]:
    """Execute an LLM task with standardized timeout resolution.

    Timeout resolution hierarchy:
        1. ``run_config.llm_timeout`` (individual action override)
        2. ``settings.llm_timeout`` (global default)
        3. Capped by ``run_config.timeout`` (action total budget)

    Args:
        prompt: The LLM prompt to send.
        system: Optional system messages.
        client: Optional AIClient override.
        run_config: Optional runtime configuration for timeout resolution.

    Returns:
        Parsed dict from the Interpreter.
    """
    if run_config is not None:
        run_config.raise_if_terminated()

    llm_timeout = settings.llm_timeout
    if run_config is not None and run_config.llm_timeout is not None:
        llm_timeout = run_config.llm_timeout
    if run_config is not None and run_config.timeout is not None and llm_timeout is not None:
        llm_timeout = min(llm_timeout, run_config.timeout)
    if run_config is not None:
        remaining = run_config.remaining()
        if remaining is not None:
            llm_timeout = min(llm_timeout, remaining) if llm_timeout is not None else remaining

    task = AITask(prompt=prompt, interpreter=Interpreter(), client=client)
    result = task.run(
        profile=LLMProfileName.ACTION_LLM,
        system=system,
        config=ChatConfig(timeout=llm_timeout),
    ).data

    if run_config is not None:
        run_config.raise_if_terminated()
    return result
