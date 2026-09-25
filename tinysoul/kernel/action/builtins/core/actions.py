"""Built-in core action executors and registrar."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import isfinite

from tinysoul.kernel.action.tasks import ActionTaskFactory, ActionTaskOutput
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.kernel.action.call import ActionExecution
from tinysoul.kernel.action.execution.executor import ActionExecutionContext
from tinysoul.kernel.action.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.kernel.action.engine import ActionEngineBuilder
from tinysoul.kernel.context import (
    PromptBlock,
    PromptReferenceError,
    PromptReferenceResolver,
    TaskPrompt,
)
from tinysoul.infra.json import JsonObject, JsonTypeError, JsonValue, to_json_object


@dataclass(frozen=True)
class _PromptParse:
    prompt: TaskPrompt | None = None
    source_links: tuple[str, ...] = ()
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
        reference_resolvers: Sequence[PromptReferenceResolver] = (),
    ) -> None:
        self._tasks, self._llm = tasks, llm
        self._prompt_builder = _PromptArgumentBuilder(
            reference_resolvers=reference_resolvers,
        )

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = await self._prompt_builder.context_task_prompt(execution.call.params)
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
    """Executor for the final answer action with read-only reference support."""

    def __init__(
        self,
        *,
        tasks: ActionTaskFactory,
        llm: LLMRunner,
        reference_resolvers: Sequence[PromptReferenceResolver] = (),
    ) -> None:
        self._tasks, self._llm = tasks, llm
        self._prompt_builder = _PromptArgumentBuilder(
            reference_resolvers=reference_resolvers,
        )

    async def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        parse = await self._prompt_builder.answer_prompt(execution.call.params)
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
            _task_result, execution, subject="Answer LLM task"
        )
        if isinstance(payload, ActionResult):
            return payload
        payload_failure = _answer_payload_failure(payload)
        if payload_failure is not None:
            return _failed(
                execution,
                payload_failure.model_feedback,
                reason=payload_failure.reason,
            )
        return _success(
            execution,
            _normalized_answer_payload(
                payload,
                source_links=parse.source_links,
            ),
        )


class CoreAskActionExecutor:
    """Produce a question intent; the Turn owns publication and waiting."""

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        params = execution.call.params
        text = params.get("text")
        options = params.get("options", [])
        timeout = params.get("timeout_seconds")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > 4000
            or not isinstance(options, list)
            or len(options) > 8
            or any(
                not isinstance(item, str) or not item or len(item) > 400
                for item in options
            )
            or (
                timeout is not None
                and (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float))
                    or not isfinite(timeout)
                    or timeout <= 0
                )
            )
        ):
            return _failed(
                execution,
                "Provide a question, optional choices and a positive timeout.",
                reason="invalid_question",
            )
        return _success(
            execution,
            {"text": text.strip(), "options": options, "timeout_seconds": timeout},
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
                "Choose a positive timeout or an explicit event kind and optional identity.",
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
    def __init__(
        self,
        *,
        reference_resolvers: Sequence[PromptReferenceResolver],
    ) -> None:
        self._reference_resolvers = tuple(reference_resolvers)

    async def context_task_prompt(self, params: JsonObject) -> _PromptParse:
        try:
            reference_links = params.get("reference_links", [])
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
                        *(await self._parse_reference_links(reference_links)),
                    ),
                    output_blocks=self._parse_blocks(
                        params.get("output_blocks"),
                        key="output_blocks",
                        section="output",
                        heading="Expected Output",
                        required=True,
                    ),
                ),
                source_links=self._source_links(reference_links),
            )
        except _PromptParameterError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                failure_reason=exc.reason,
                frame_data=exc.payload,
            )
        except PromptReferenceError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                failure_reason=exc.reason,
                frame_data=exc.payload,
            )

    async def answer_prompt(self, params: JsonObject) -> _PromptParse:
        try:
            reference_links = params.get("reference_links", [])
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
                        *(await self._parse_reference_links(reference_links)),
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
                source_links=self._source_links(reference_links),
            )
        except _PromptParameterError as exc:
            return _PromptParse(
                model_feedback=str(exc),
                failure_reason=exc.reason,
                frame_data=exc.payload,
            )
        except PromptReferenceError as exc:
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
                    f"Model task requires non-empty '{key}'.",
                    reason=f"missing_{key}",
                )
            return ()
        if not isinstance(value, list):
            raise _PromptParameterError(
                f"Model task '{key}' must be a list.",
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
                f"Model task requires non-empty '{key}'.",
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
                f"Model task '{key}' items must be objects.",
                reason=f"invalid_{key}_item",
                payload={"index": index},
            ) from exc
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise _PromptParameterError(
                f"Model task '{key}' items require non-empty text.",
                reason=f"invalid_{key}_text",
                payload={"index": index},
            )
        label_value = item.get("label")
        if label_value is not None and (
            not isinstance(label_value, str) or not label_value
        ):
            raise _PromptParameterError(
                f"Model task '{key}' label must be non-empty when provided.",
                reason=f"invalid_{key}_label",
                payload={"index": index},
            )
        label_suffix = label_value if isinstance(label_value, str) else str(index)
        return PromptBlock.from_text(
            f"task_prompt:{section}:{label_suffix}",
            f"# {heading}\n{text}",
        )

    async def _parse_reference_links(self, value: object) -> tuple[PromptBlock, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise PromptReferenceError(
                "Model task 'reference_links' must be a list when provided.",
                reason="invalid_reference_links",
            )
        blocks: list[PromptBlock] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, str) or not item:
                raise PromptReferenceError(
                    "Model task 'reference_links' items must be non-empty strings.",
                    reason="invalid_reference_link",
                    payload={"index": index},
                )
            resolver = self._resolver_for(item)
            if resolver is None:
                raise PromptReferenceError(
                    f"Unsupported task prompt reference link: {item}",
                    reason="unsupported_reference_link",
                    payload={"index": index, "link": item},
                )
            resolved = await resolver.resolve_reference(item)
            if not resolved:
                raise PromptReferenceError(
                    f"Task prompt reference produced no content: {item}",
                    reason="empty_reference",
                    payload={"index": index, "link": item},
                )
            blocks.extend(resolved)
        return tuple(blocks)

    def _source_links(self, value: object) -> tuple[str, ...]:
        if value is None or not isinstance(value, list):
            return ()
        links: list[str] = []
        for item in value:
            if isinstance(item, str) and item and item not in links:
                links.append(item)
        return tuple(links)

    def _resolver_for(self, link: str) -> PromptReferenceResolver | None:
        for resolver in self._reference_resolvers:
            if resolver.supports(link):
                return resolver
        return None


@dataclass(frozen=True)
class _PayloadFailure:
    model_feedback: str
    reason: str


def _answer_payload_failure(payload: JsonObject) -> _PayloadFailure | None:
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        return _PayloadFailure(
            "Answer LLM task must return a JSON object with non-empty string field 'text'.",
            "invalid_answer_text",
        )
    references = payload.get("references")
    if references is None:
        return None
    if not isinstance(references, list):
        return _PayloadFailure(
            "Answer LLM task 'references' field must be a string array.",
            "invalid_answer_references",
        )
    for item in references:
        if not isinstance(item, str) or not item:
            return _PayloadFailure(
                "Answer LLM task 'references' field must contain non-empty strings.",
                "invalid_answer_references",
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


def register_core_actions(
    builder: ActionEngineBuilder,
    *,
    tasks: ActionTaskFactory,
    llm: LLMRunner,
    reference_resolvers: Sequence[PromptReferenceResolver] = (),
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
                reference_resolvers=reference_resolvers,
            ),
        )
        .register_executor(
            "core.answer",
            CoreAnswerActionExecutor(
                tasks=tasks,
                llm=llm,
                reference_resolvers=reference_resolvers,
            ),
        )
    )


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
