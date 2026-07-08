"""LLM-step action executor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.context import (
    ContextEngine,
    PromptBlock,
    PromptReferenceError,
    PromptReferenceResolver,
    TaskPrompt,
)
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject, JsonTypeError, JsonValue, to_json_object
from tinysoul.llm.requests import CallSettings, TaskCall, TaskProfile
from tinysoul.llm.responses import AnswerFormat, JsonAnswer, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolUse
from tinysoul.runtime import RuntimeException


class LLMRunner(Protocol):
    """LLM runner surface required by the LLM-step executor."""

    def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task."""
        ...


@dataclass(frozen=True)
class _PromptParse:
    prompt: TaskPrompt | None = None
    source_links: tuple[str, ...] = ()
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
        self._prompt_builder = _PromptArgumentBuilder(
            reference_resolvers=reference_resolvers,
        )

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = self._prompt_builder.context_task_prompt(execution.call.params)
        if parse.prompt is None:
            return _failed(execution, parse.model_feedback, parse.frame_data)
        payload = _run_json_task(
            llm_runner=self._llm_runner,
            context_engine=self._context,
            execution=execution,
            prompt=parse.prompt,
            subject="Nested LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        return _success(execution, payload)


class LLMAnswerActionExecutor:
    """Executor for the final answer action with workspace reference support."""

    def __init__(
        self,
        *,
        llm_runner: LLMRunner,
        context: ContextEngine,
        reference_resolvers: Sequence[PromptReferenceResolver] = (),
    ) -> None:
        self._llm_runner = llm_runner
        self._context = context
        self._prompt_builder = _PromptArgumentBuilder(
            reference_resolvers=reference_resolvers,
        )

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = self._prompt_builder.answer_prompt(execution.call.params)
        if parse.prompt is None:
            return _failed(execution, parse.model_feedback, parse.frame_data)
        payload = _run_json_task(
            llm_runner=self._llm_runner,
            context_engine=self._context,
            execution=execution,
            prompt=parse.prompt,
            subject="Answer LLM task",
        )
        if isinstance(payload, ActionResult):
            return payload
        payload_failure = _answer_payload_failure(payload)
        if payload_failure is not None:
            return _failed(
                execution,
                payload_failure.model_feedback,
                payload_failure.frame_data,
            )
        return _success(
            execution,
            _normalized_answer_payload(
                payload,
                source_links=parse.source_links,
            ),
        )


class _PromptArgumentBuilder:
    def __init__(
        self,
        *,
        reference_resolvers: Sequence[PromptReferenceResolver],
    ) -> None:
        self._reference_resolvers = tuple(reference_resolvers)

    def context_task_prompt(self, params: JsonObject) -> _PromptParse:
        try:
            return _PromptParse(
                prompt=TaskPrompt(
                    guide_blocks=self._parse_blocks(
                        params.get("guide_blocks"),
                        key="guide_blocks",
                        section="guide",
                        heading="Task Guide",
                        required=True,
                    ),
                    input_blocks=(
                        *self._parse_blocks(
                            params.get("input_blocks", []),
                            key="input_blocks",
                            section="input",
                            heading="Task Input",
                        ),
                        *self._parse_resolved_blocks(
                            params.get("targets", []),
                            key="targets",
                        ),
                        *self._parse_resolved_blocks(
                            params.get("references", []),
                            key="references",
                        ),
                    ),
                    output_blocks=self._parse_blocks(
                        params.get("output_blocks"),
                        key="output_blocks",
                        section="output",
                        heading="Expected Output",
                        required=True,
                    ),
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

    def answer_prompt(self, params: JsonObject) -> _PromptParse:
        try:
            references = params.get("references", [])
            return _PromptParse(
                prompt=TaskPrompt(
                    guide_blocks=self._parse_blocks(
                        params.get("guide_blocks"),
                        key="guide_blocks",
                        section="guide",
                        heading="Answer Guide",
                        required=True,
                    ),
                    input_blocks=(
                        *self._parse_blocks(
                            params.get("input_blocks", []),
                            key="input_blocks",
                            section="input",
                            heading="Answer Input",
                        ),
                        *self._parse_resolved_blocks(
                            references,
                            key="references",
                        ),
                    ),
                    output_blocks=(
                        PromptBlock.from_text(
                            "task_prompt:output:answer",
                            (
                                "# Expected Output\n"
                                "Return a JSON object with a string field 'text'. "
                                "If source links are used, include a 'references' "
                                "array of source link strings."
                            ),
                        ),
                    ),
                ),
                source_links=self._source_links(references),
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
                    f"llm_step requires non-empty '{key}'.",
                    reason=f"missing_{key}",
                )
            return ()
        if not isinstance(value, list):
            raise _PromptParameterError(
                f"llm_step '{key}' must be a list.",
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
                f"llm_step requires non-empty '{key}'.",
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
                f"llm_step '{key}' items must be objects.",
                reason=f"invalid_{key}_item",
                payload={"index": index},
            ) from exc
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise _PromptParameterError(
                f"llm_step '{key}' items require non-empty text.",
                reason=f"invalid_{key}_text",
                payload={"index": index},
            )
        label_value = item.get("label")
        if label_value is not None and (
            not isinstance(label_value, str) or not label_value
        ):
            raise _PromptParameterError(
                f"llm_step '{key}' label must be non-empty when provided.",
                reason=f"invalid_{key}_label",
                payload={"index": index},
            )
        label_suffix = label_value if isinstance(label_value, str) else str(index)
        return PromptBlock.from_text(
            f"task_prompt:{section}:{label_suffix}",
            f"# {heading}\n{text}",
        )

    def _parse_resolved_blocks(self, value: object, *, key: str) -> tuple[PromptBlock, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise PromptReferenceError(
                f"llm_step '{key}' must be a list when provided.",
                reason=f"invalid_{key}",
            )
        blocks: list[PromptBlock] = []
        for index, item in enumerate(value, start=1):
            reference = self._reference_item(item, index=index, key=key)
            kind = reference.get("type")
            if not isinstance(kind, str) or not kind:
                raise PromptReferenceError(
                    f"llm_step '{key}' items require a non-empty type.",
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

    def _source_links(self, value: object) -> tuple[str, ...]:
        if value is None or not isinstance(value, list):
            return ()
        links: list[str] = []
        for index, item in enumerate(value, start=1):
            reference = self._reference_item(item, index=index, key="references")
            link = reference.get("link")
            if isinstance(link, str) and link and link not in links:
                links.append(link)
        return tuple(links)

    def _reference_item(self, value: object, *, index: int, key: str) -> JsonObject:
        try:
            return to_json_object(value)
        except JsonTypeError as exc:
            raise PromptReferenceError(
                f"llm_step '{key}' items must be objects.",
                reason="invalid_reference",
                payload={"index": index},
            ) from exc

    def _resolver_for(self, kind: str) -> PromptReferenceResolver | None:
        for resolver in self._reference_resolvers:
            if resolver.supports(kind):
                return resolver
        return None


def _run_json_task(
    *,
    llm_runner: LLMRunner,
    context_engine: ContextEngine,
    execution: ActionExecution,
    prompt: TaskPrompt,
    subject: str,
) -> JsonObject | ActionResult:
    try:
        result = llm_runner.run(
            TaskCall(
                profile=TaskProfile.LLM_ACTION,
                messages=context_engine.compose(prompt),
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                ),
            )
        )
    except RuntimeException as exc:
        return _failed(
            execution,
            f"{subject} failed: {exc.message}",
            {"reason": exc.reason, "payload": exc.payload},
        )
    except ContextError as exc:
        return _failed(
            execution,
            f"{subject} could not compose context: {exc}",
            {"error_type": type(exc).__name__},
        )
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


@dataclass(frozen=True)
class _PayloadFailure:
    model_feedback: str
    frame_data: JsonObject


def _answer_payload_failure(payload: JsonObject) -> _PayloadFailure | None:
    text = payload.get("text")
    if not isinstance(text, str):
        return _PayloadFailure(
            "Answer LLM task must return a JSON object with string field 'text'.",
            {"reason": "invalid_answer_text"},
        )
    references = payload.get("references")
    if references is None:
        return None
    if not isinstance(references, list):
        return _PayloadFailure(
            "Answer LLM task 'references' field must be a string array.",
            {"reason": "invalid_answer_references"},
        )
    for item in references:
        if not isinstance(item, str) or not item:
            return _PayloadFailure(
                "Answer LLM task 'references' field must contain non-empty strings.",
                {"reason": "invalid_answer_references"},
            )
    return None


def _normalized_answer_payload(
    payload: JsonObject,
    *,
    source_links: tuple[str, ...],
) -> JsonObject:
    result: JsonObject = {"text": payload["text"]}
    references_value: JsonValue = payload.get("references", [])
    references: list[JsonValue] = []
    if isinstance(references_value, list):
        references.extend(
            item for item in references_value if isinstance(item, str) and item
        )
    if not references:
        references.extend(source_links)
    if references:
        result["references"] = references
    return result


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
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
