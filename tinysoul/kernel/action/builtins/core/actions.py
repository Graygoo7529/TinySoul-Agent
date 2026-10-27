"""Built-in core action executors and registrar."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object
from tinysoul.infra.references import markdown_references
from tinysoul.kernel.action.call import ActionExecution
from tinysoul.kernel.action.engine import ActionEngineBuilder
from tinysoul.kernel.action.execution.executor import ActionExecutionContext
from tinysoul.kernel.action.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.kernel.action.tasks import ActionTaskFactory, ActionTaskOutput
from tinysoul.kernel.context import PromptBlock, TaskPrompt
from tinysoul.kernel.interaction import QuestionContent, QuestionError
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.prompts.kernel import action as prompt_text


@dataclass(frozen=True)
class _PromptParse:
    prompt: TaskPrompt | None = None
    model_feedback: str = ""
    failure_reason: str = ""
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


class CoreReasonActionExecutor:
    """Executor for the generic core.reason action."""

    def __init__(
        self,
        *,
        tasks: ActionTaskFactory,
        llm: LLMRunner,
    ) -> None:
        self._tasks, self._llm = tasks, llm
        self._prompt_builder = _PromptArgumentBuilder()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = self._prompt_builder.context_task_prompt(execution.call.params)
        if parse.prompt is None:
            return _failed(
                execution,
                parse.model_feedback,
                reason=parse.failure_reason,
                frame_data=parse.frame_data,
            )
        _task_result = await self._llm.run(
            await self._tasks.create(
                execution=execution,
                prompt=parse.prompt,
                control=context.control,
                consumer=f"{execution.call.action_name}.generate",
                answer_format=AnswerFormat.JSON_OBJECT,
            )
        )
        payload = ActionTaskOutput.json(
            _task_result, execution, subject="Core reason LLM task"
        )
        if isinstance(payload, ActionResult):
            return payload
        return _success(execution, payload)


class CoreAnswerActionExecutor:
    """Generate the answer body and package its explicit resource citations."""

    def __init__(
        self,
        *,
        tasks: ActionTaskFactory,
        llm: LLMRunner,
    ) -> None:
        self._tasks, self._llm = tasks, llm
        self._prompt_builder = _PromptArgumentBuilder()

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = self._prompt_builder.answer_prompt(execution.call.params)
        if parse.prompt is None:
            return _failed(
                execution,
                parse.model_feedback,
                reason=parse.failure_reason,
                frame_data=parse.frame_data,
            )
        _task_result = await self._llm.run(
            await self._tasks.create(
                execution=execution,
                prompt=parse.prompt,
                control=context.control,
                consumer=f"{execution.call.action_name}.generate",
                answer_format=AnswerFormat.TEXT,
            )
        )
        text = ActionTaskOutput.text(
            _task_result, execution, subject="Answer generation"
        )
        if isinstance(text, ActionResult):
            return text
        return _success(
            execution,
            {"text": text, "references": list(_answer_references(text))},
        )


class CoreAskActionExecutor:
    """Produce a question intent; the Turn owns publication and waiting."""

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        params = execution.call.params
        timeout = params.get("timeout_seconds")
        try:
            if set(params) - {
                "question",
                "details",
                "options",
                "allow_other",
                "timeout_seconds",
            }:
                raise QuestionError("Question has unknown fields")
            question = QuestionContent.from_json(params)
            if timeout is not None and (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not isfinite(timeout)
                or timeout <= 0
            ):
                raise QuestionError("Question timeout must be positive")
        except QuestionError:
            return _failed(
                execution,
                prompt_text.INVALID_QUESTION,
                reason="invalid_question",
            )
        return _success(
            execution,
            {
                **question.to_json(),
                "timeout_seconds": timeout,
            },
            model_text=question.narrative(),
        )


class CoreWaitActionExecutor:
    """Accept a bounded wait intent; execution never waits inside Phase3."""

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        params = execution.call.params
        timeout, kind, event_id = (
            params.get("timeout_seconds"),
            params.get("event_kind"),
            params.get("event_id"),
        )
        topic, source = params.get("topic"), params.get("source")
        if kind is None and (topic is not None or source is not None):
            kind = "event"
        if (
            (
                timeout is not None
                and (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float))
                    or not isfinite(timeout)
                    or timeout <= 0
                )
            )
            or kind not in {None, "event", "timer", "job"}
            or (
                event_id is not None
                and (not isinstance(event_id, str) or not event_id or kind is None)
            )
            or (timeout is None and kind is None)
            or any(
                value is not None and (not isinstance(value, str) or not value)
                for value in (topic, source)
            )
        ):
            return _failed(
                execution,
                prompt_text.INVALID_WAIT,
                reason="invalid_wait",
            )
        return _success(
            execution,
            {
                "timeout_seconds": timeout,
                "event_kind": kind,
                "event_id": event_id,
                "topic": topic,
                "source": source,
            },
        )


class _PromptArgumentBuilder:
    def context_task_prompt(self, params: JsonObject) -> _PromptParse:
        try:
            return _PromptParse(
                prompt=TaskPrompt(
                    guide_blocks=self._parse_blocks(
                        params.get("guide_blocks"),
                        key="guide_blocks",
                        section="guide",
                        heading=prompt_text.TASK_GUIDE_HEADING,
                        required=True,
                    ),
                    input_blocks=self._parse_blocks(
                        params.get("input_blocks", []),
                        key="input_blocks",
                        section="input",
                        heading=prompt_text.TASK_INPUT_HEADING,
                    ),
                    output_blocks=self._parse_blocks(
                        params.get("output_blocks"),
                        key="output_blocks",
                        section="output",
                        heading=prompt_text.EXPECTED_OUTPUT_HEADING,
                        required=True,
                    ),
                ),
            )
        except _PromptParameterError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                failure_reason=exc.reason,
                frame_data=exc.payload,
            )

    def answer_prompt(self, params: JsonObject) -> _PromptParse:
        try:
            return _PromptParse(
                prompt=TaskPrompt(
                    guide_blocks=self._parse_blocks(
                        params.get("guide_blocks"),
                        key="guide_blocks",
                        section="guide",
                        heading=prompt_text.ANSWER_GUIDE_HEADING,
                        required=True,
                    ),
                    input_blocks=self._parse_blocks(
                        params.get("input_blocks", []),
                        key="input_blocks",
                        section="input",
                        heading=prompt_text.ANSWER_INPUT_HEADING,
                    ),
                    output_blocks=(
                        PromptBlock.from_text(
                            "task_prompt:output:answer",
                            prompt_text.ANSWER_EXPECTED_OUTPUT,
                        ),
                    ),
                ),
            )
        except _PromptParameterError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                failure_reason=exc.reason,
                frame_data=exc.payload,
            )

    def _parse_blocks(
        self,
        value: object,
        *,
        key: str,
        section: str,
        heading: str,
        required: bool = False,
    ) -> tuple[PromptBlock, ...]:
        if value is None:
            if required:
                raise _PromptParameterError(
                    prompt_text.required_prompt_blocks(key=key),
                    reason=f"missing_{key}",
                )
            return ()
        if not isinstance(value, list):
            raise _PromptParameterError(
                prompt_text.prompt_blocks_must_be_list(key=key),
                reason=f"invalid_{key}",
            )
        blocks: list[PromptBlock] = []
        for index, item in enumerate(value, start=1):
            blocks.append(
                self._parse_block_item(
                    item,
                    key=key,
                    index=index,
                    section=section,
                    heading=heading,
                )
            )
        if required and not blocks:
            raise _PromptParameterError(
                prompt_text.required_prompt_blocks(key=key),
                reason=f"missing_{key}",
            )
        return tuple(blocks)

    def _parse_block_item(
        self,
        value: object,
        *,
        key: str,
        index: int,
        section: str,
        heading: str,
    ) -> PromptBlock:
        try:
            item = to_json_object(value)
        except JsonTypeError as exc:
            raise _PromptParameterError(
                prompt_text.prompt_blocks_must_be_objects(key=key),
                reason=f"invalid_{key}_item",
                payload={"index": index},
            ) from exc
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise _PromptParameterError(
                prompt_text.prompt_block_text_required(key=key),
                reason=f"invalid_{key}_text",
                payload={"index": index},
            )
        label_value = item.get("label")
        if label_value is not None and (
            not isinstance(label_value, str) or not label_value
        ):
            raise _PromptParameterError(
                prompt_text.prompt_block_label_required(key=key),
                reason=f"invalid_{key}_label",
                payload={"index": index},
            )
        label_suffix = label_value if isinstance(label_value, str) else str(index)
        return PromptBlock.from_text(
            f"task_prompt:{section}:{label_suffix}",
            prompt_text.task_block(heading=heading, text=text),
        )


def _answer_references(text: str) -> tuple[str, ...]:
    """Record explicit internal links, without loading or verifying their targets."""
    return tuple(
        dict.fromkeys(
            link.target
            for link in markdown_references(text)
            if link.target.startswith(
                ("home:", "memory:", "workspace:", "session:", "turn:")
            )
        )
    )


def register_core_actions(
    builder: ActionEngineBuilder,
    *,
    tasks: ActionTaskFactory,
    llm: LLMRunner,
) -> ActionEngineBuilder:
    """Register built-in core actions on an action builder."""

    return (
        builder.register_executor(
            "core.ask",
            CoreAskActionExecutor(),
        )
        .register_executor(
            "core.wait",
            CoreWaitActionExecutor(),
        )
        .register_executor(
            "core.reason",
            CoreReasonActionExecutor(
                tasks=tasks,
                llm=llm,
            ),
        )
        .register_executor(
            "core.answer",
            CoreAnswerActionExecutor(
                tasks=tasks,
                llm=llm,
            ),
        )
    )


def _success(
    execution: ActionExecution, payload: JsonObject, *, model_text: str | None = None
) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
        model_text=model_text,
    )


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    *,
    reason: str,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope="core.output_protocol",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=model_feedback,
        ),
        frame_data=frame_data,
    )
