"""Registration helpers for LLM-step action executors."""

from __future__ import annotations

from collections.abc import Sequence

from tinysoul.action.engine import ActionEngineBuilder
from tinysoul.context import ContextEngine

from .llm_step import LLMRunner, LLMStepActionExecutor, PromptReferenceResolver


def register_llm_step_actions(
    builder: ActionEngineBuilder,
    *,
    llm_runner: LLMRunner,
    context: ContextEngine,
    reference_resolvers: Sequence[PromptReferenceResolver] = (),
) -> ActionEngineBuilder:
    """Register built-in LLM-step action executors on an action builder."""

    return builder.register_executor(
        "llm_step.context_task",
        LLMStepActionExecutor(
            llm_runner=llm_runner,
            context=context,
            reference_resolvers=reference_resolvers,
        ),
    )
