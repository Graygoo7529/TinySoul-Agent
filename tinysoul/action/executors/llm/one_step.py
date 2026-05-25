"""Concrete action executor implementations for TinySoul.

These are plugin-level executors that depend on AI infrastructure.
The base ActionExecutor interface lives in tinysoul.action.framework.executor.

On failure, executors raise TinysoulError exceptions rather than returning
error JSON. The ActionBase boundary wrapper catches unknown
exceptions and promotes them to ActionExecutionError.
"""

from typing import Any, Callable

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.prompt.action import (
    build_llm_action_system,
    get_one_step_default_system,
)
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError
from tinysoul.llm.tasks import (
    LLMPrompt,
    PromptBuilder,
)
from tinysoul.context.workspace import Workspace

from ._common import run_llm_task


class OneStepAIExecutor(ActionExecutor):
    """
    Executor for single-step AI-dependent actions.

    Template method: parse → build prompt → AI call → parse response → apply result

    On failure, raises ActionExecutionError (or other TinysoulError)
    instead of returning JSON error strings.
    """

    def __init__(
        self,
        build_prompt: Callable[[PromptBuilder, dict[str, Any], Workspace], LLMPrompt],
        apply_result: Callable[
            [dict[str, Any], dict[str, Any], Workspace, ContextProvider], Any
        ],
        system_prompt: list[dict[str, str]] | None = None,
        client: Any | None = None,
    ):
        self._build_prompt = build_prompt
        self._apply_result = apply_result
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._client = client

    def _default_system_prompt(self) -> list[dict[str, str]]:
        return get_one_step_default_system()

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider,
        run_config: RunConfig,
    ) -> dict:
        if context_provider is None or context_provider.workspace is None:
            raise ActionExecutionError("This action requires workspace in context")
        run_config.raise_if_terminated()

        workspace = context_provider.workspace
        params = action_input

        builder = PromptBuilder(context_provider)
        prompt = self._build_prompt(builder, params, workspace)

        full_system = build_llm_action_system(
            context_provider,
            action_system=self._system_prompt,
        )

        client = self._client
        if client is None and context_provider is not None:
            client = getattr(context_provider, "client", None)

        generated = run_llm_task(
            prompt=prompt,
            system=full_system,
            client=client,
            run_config=run_config,
        )

        result = self._apply_result(params, generated, workspace, context_provider)
        run_config.raise_if_terminated()
        return result
