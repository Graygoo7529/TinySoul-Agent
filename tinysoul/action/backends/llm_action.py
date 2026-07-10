"""Action backend support for nested LLM tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.context import ContextEngine, PromptBlock, TaskPrompt
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.requests import CallSettings, TaskCall, TaskProfile
from tinysoul.llm.responses import AnswerFormat, JsonAnswer, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolUse
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.bridge import RuntimeContextBridge


class LLMActionModelRunner(Protocol):
    """LLM runner surface required by action-internal LLM tasks."""

    def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task."""
        ...


@dataclass(frozen=True)
class ActionHow:
    """HOW snippets automatically mounted for one action-internal LLM task."""

    domain: tuple[str, ...] = ()
    action: tuple[str, ...] = ()


class ActionHowProvider(Protocol):
    """Provide domain and action HOW text for nested LLM tasks."""

    def guidance_for(self, *, domain: str, action_name: str) -> ActionHow:
        """Return HOW snippets for one action execution."""
        ...


class EmptyActionHowProvider:
    """Action HOW provider used before Agent Home action HOW is connected."""

    def guidance_for(self, *, domain: str, action_name: str) -> ActionHow:
        return ActionHow()


class LLMActionTaskRunner:
    """Run action-internal LLM tasks using Context-built message stacks."""

    def __init__(
        self,
        *,
        llm_runner: LLMActionModelRunner,
        context: ContextEngine,
        action_how: ActionHowProvider | None = None,
        context_bridge: RuntimeContextBridge | None = None,
    ) -> None:
        self._llm_runner = llm_runner
        self._context = context
        self._action_how = action_how or EmptyActionHowProvider()
        self._context_bridge = context_bridge or RuntimeContextBridge()

    def prompt_with_how(
        self,
        prompt: TaskPrompt,
        *,
        execution: ActionExecution,
    ) -> TaskPrompt:
        """Return a prompt with Phase3 domain/action HOW appended."""

        return with_action_how(
            prompt,
            self._action_how.guidance_for(
                domain=execution.framework.domain,
                action_name=execution.call.action_name,
            ),
        )

    def run_json(
        self,
        *,
        execution: ActionExecution,
        prompt: TaskPrompt,
        subject: str,
    ) -> JsonObject | ActionResult:
        """Run one JSON-object LLM action task and normalize local failures."""

        prompt = self.prompt_with_how(prompt, execution=execution)
        try:
            result = self._llm_runner.run(
                TaskCall(
                    profile=TaskProfile.LLM_ACTION,
                    messages=self._context.compose(prompt),
                    settings=CallSettings(
                        answer_format=AnswerFormat.JSON_OBJECT,
                        tool_use=ToolUse.DISABLED,
                    ),
                )
            )
        except RuntimeException:
            raise
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc
        if result.status is TaskResultStatus.FAILURE:
            feedback = f"{subject} output did not satisfy its protocol."
            if result.failure is not None and result.failure.model_feedback:
                feedback = result.failure.model_feedback
            return _failed(execution, feedback, {"reason": "task_failure"})
        if not isinstance(result.answer, JsonAnswer):
            return _failed(
                execution,
                f"{subject} did not return a JSON object.",
                {"reason": "missing_json_answer"},
            )
        return result.answer.value


def with_action_how(prompt: TaskPrompt, how: ActionHow) -> TaskPrompt:
    """Return a prompt with Phase3 domain/action HOW guide blocks appended."""

    if not how.domain and not how.action:
        return prompt
    guide_blocks = [*prompt.guide_blocks]
    for index, item in enumerate(how.domain, start=1):
        if item:
            guide_blocks.append(
                PromptBlock.from_text(
                    f"task_prompt:guide:domain_how:{index}",
                    "# Domain HOW\n" + item,
                )
            )
    for index, item in enumerate(how.action, start=1):
        if item:
            guide_blocks.append(
                PromptBlock.from_text(
                    f"task_prompt:guide:action_how:{index}",
                    "# Action HOW\n" + item,
                )
            )
    return TaskPrompt(
        guide_blocks=tuple(guide_blocks),
        input_blocks=prompt.input_blocks,
        output_blocks=prompt.output_blocks,
    )


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    frame_data: JsonObject,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        frame_data=frame_data,
    )
