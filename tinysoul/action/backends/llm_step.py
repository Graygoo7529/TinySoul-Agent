"""LLM-step action executor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.context import ContextEngine, PromptBlock, TaskPrompt
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object
from tinysoul.llm.requests import CallSettings, TaskCall, TaskProfile
from tinysoul.llm.responses import AnswerFormat, JsonAnswer, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolUse
from tinysoul.runtime import RuntimeException


class LLMRunner(Protocol):
    """LLM runner surface required by the LLM-step executor."""

    def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task."""
        ...


class PromptReferenceError(Exception):
    """Raised when a task prompt reference cannot be resolved."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "prompt_reference_error",
        payload: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.payload = payload or {}


class PromptReferenceResolver(Protocol):
    """Resolve structured task prompt references into prompt blocks."""

    def supports(self, kind: str) -> bool:
        """Return whether this resolver handles a reference kind."""
        ...

    def resolve(self, reference: JsonObject) -> tuple[PromptBlock, ...]:
        """Resolve one structured reference into prompt blocks."""
        ...


@dataclass(frozen=True)
class _PromptParse:
    prompt: TaskPrompt | None = None
    model_feedback: str = ""
    frame_data: JsonObject = field(default_factory=dict)


class _PromptParameterError(Exception):
    def __init__(
        self,
        message: str,
        *,
        reason: str,
        payload: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.payload = payload or {}


class LLMStepActionExecutor:
    """Executor for actions that need one nested LLM task."""

    def __init__(
        self,
        *,
        llm_runner: LLMRunner,
        context: ContextEngine,
        reference_resolvers: Sequence[PromptReferenceResolver] = (),
    ) -> None:
        self._llm_runner = llm_runner
        self._context = context
        self._reference_resolvers = tuple(reference_resolvers)

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = self._prompt(execution)
        if parse.prompt is None:
            return self._failed(
                execution,
                parse.model_feedback,
                parse.frame_data,
            )
        try:
            result = self._llm_runner.run(
                TaskCall(
                    profile=TaskProfile.LLM_ACTION,
                    messages=self._context.compose(parse.prompt),
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

    def _prompt(self, execution: ActionExecution) -> _PromptParse:
        guide = execution.call.params.get("guide")
        if not isinstance(guide, str) or not guide:
            return _PromptParse(
                model_feedback="llm_step requires a non-empty 'guide' parameter.",
                frame_data={"reason": "missing_guide"},
            )
        output_desc = execution.call.params.get("output_desc", "")
        if not isinstance(output_desc, str):
            return _PromptParse(
                model_feedback="llm_step output_desc must be a string when provided.",
                frame_data={"reason": "invalid_output_desc"},
            )
        try:
            task_inputs = list(
                self._parse_legacy_task_input(execution.call.params.get("task_input"))
            )
            task_inputs.extend(
                self._parse_task_inputs(execution.call.params.get("task_inputs", []))
            )
            task_inputs.extend(
                self._parse_references(execution.call.params.get("references", []))
            )
            return _PromptParse(
                prompt=TaskPrompt(
                    guide=guide,
                    output_desc=output_desc,
                    task_inputs=tuple(task_inputs),
                )
            )
        except _PromptParameterError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                frame_data={**exc.payload, "reason": exc.reason},
            )
        except PromptReferenceError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                frame_data={**exc.payload, "reason": exc.reason},
            )

    def _parse_legacy_task_input(self, value: object) -> tuple[PromptBlock, ...]:
        if value is None:
            return ()
        if not isinstance(value, str):
            raise _PromptParameterError(
                "llm_step task_input must be a string when provided.",
                reason="invalid_task_input",
            )
        if not value:
            return ()
        return (
            PromptBlock.from_text(
                "task_prompt:input",
                f"# Task Input\n{value}",
            ),
        )

    def _parse_task_inputs(self, value: object) -> tuple[PromptBlock, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise _PromptParameterError(
                "llm_step task_inputs must be a list when provided.",
                reason="invalid_task_inputs",
            )
        blocks: list[PromptBlock] = []
        for index, item in enumerate(value, start=1):
            try:
                task_input = to_json_object(item)
            except JsonTypeError as exc:
                raise _PromptParameterError(
                    "llm_step task_inputs items must be objects.",
                    reason="invalid_task_input_item",
                    payload={"index": index},
                ) from exc
            text = task_input.get("text")
            if not isinstance(text, str) or not text:
                raise _PromptParameterError(
                    "llm_step task_inputs items require non-empty text.",
                    reason="invalid_task_input_text",
                    payload={"index": index},
                )
            label_value = task_input.get("label")
            if label_value is not None and (
                not isinstance(label_value, str) or not label_value
            ):
                raise _PromptParameterError(
                    "llm_step task_inputs label must be non-empty when provided.",
                    reason="invalid_task_input_label",
                    payload={"index": index},
                )
            label = (
                f"task_prompt:input:{label_value}"
                if isinstance(label_value, str)
                else f"task_prompt:input:{index}"
            )
            blocks.append(
                PromptBlock.from_text(
                    label,
                    f"# Task Input\n{text}",
                )
            )
        return tuple(blocks)

    def _parse_references(self, value: object) -> tuple[PromptBlock, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise PromptReferenceError(
                "llm_step references must be a list when provided.",
                reason="invalid_references",
            )
        blocks: list[PromptBlock] = []
        for index, item in enumerate(value, start=1):
            try:
                reference = to_json_object(item)
            except JsonTypeError as exc:
                raise PromptReferenceError(
                    "llm_step references items must be objects.",
                    reason="invalid_reference",
                    payload={"index": index},
                ) from exc
            kind = reference.get("type")
            if not isinstance(kind, str) or not kind:
                raise PromptReferenceError(
                    "llm_step references items require a non-empty type.",
                    reason="missing_reference_type",
                    payload={"index": index},
                )
            resolver = self._resolver_for(kind)
            if resolver is None:
                raise PromptReferenceError(
                    f"Unsupported task prompt reference type: {kind}",
                    reason="unsupported_reference_type",
                    payload={"index": index, "type": kind},
                )
            resolved = resolver.resolve(reference)
            if not resolved:
                raise PromptReferenceError(
                    f"Task prompt reference produced no content: {kind}",
                    reason="empty_reference",
                    payload={"index": index, "type": kind},
                )
            blocks.extend(resolved)
        return tuple(blocks)

    def _resolver_for(self, kind: str) -> PromptReferenceResolver | None:
        for resolver in self._reference_resolvers:
            if resolver.supports(kind):
                return resolver
        return None

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
