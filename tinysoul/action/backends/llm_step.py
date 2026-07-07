"""LLM-step action executor."""

from __future__ import annotations

from typing import Protocol

from tinysoul.infra.json import JsonObject
from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.context import ContextEngine, TaskPrompt
from tinysoul.context.errors import ContextError
from tinysoul.llm.requests import CallSettings, TaskCall, TaskProfile
from tinysoul.llm.responses import AnswerFormat, JsonAnswer, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolUse
from tinysoul.runtime import RuntimeException


class LLMRunner(Protocol):
    """LLM runner surface required by the LLM-step executor."""

    def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task."""
        ...


class LLMStepActionExecutor:
    """Executor for actions that need one nested LLM task."""

    def __init__(self, *, llm_runner: LLMRunner, context: ContextEngine) -> None:
        self._llm_runner = llm_runner
        self._context = context

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        prompt = self._prompt(execution)
        if prompt is None:
            return self._failed(
                execution,
                "llm_step requires a non-empty 'guide' parameter.",
                {"reason": "missing_guide"},
            )
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
        except RuntimeException as exc:
            return self._failed(
                execution,
                f"Nested LLM task failed: {exc.message}",
                {"reason": exc.reason, "payload": exc.payload},
            )
        except ContextError as exc:
            return self._failed(
                execution,
                f"Nested LLM task could not compose context: {exc}",
                {"error_type": type(exc).__name__},
            )
        if result.status is TaskResultStatus.FAILURE:
            feedback = "Nested LLM task output did not satisfy its protocol."
            if result.failure is not None and result.failure.model_feedback:
                feedback = result.failure.model_feedback
            return self._failed(
                execution,
                feedback,
                {"reason": "task_failure"},
            )
        if not isinstance(result.answer, JsonAnswer):
            return self._failed(
                execution,
                "Nested LLM task did not return a JSON object.",
                {"reason": "missing_json_answer"},
            )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=result.answer.value,
        )

    def _prompt(self, execution: ActionExecution) -> TaskPrompt | None:
        guide = execution.call.params.get("guide")
        if not isinstance(guide, str) or not guide:
            return None
        task_input = execution.call.params.get("task_input", "")
        output_desc = execution.call.params.get("output_desc", "")
        return TaskPrompt(
            guide=guide,
            task_input=task_input if isinstance(task_input, str) else "",
            output_desc=output_desc if isinstance(output_desc, str) else "",
        )

    def _failed(
        self,
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
