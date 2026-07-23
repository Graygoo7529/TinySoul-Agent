"""Built-in core action executors and registrar."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
)
from tinysoul.action.engine import ActionEngineBuilder
from tinysoul.context import (
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
        llm_action: LLMActionTaskRunner,
        reference_resolvers: Sequence[PromptReferenceResolver] = (),
    ) -> None:
        self._llm_action = llm_action
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
            return _failed(
                execution,
                parse.model_feedback,
                reason=parse.failure_reason,
                frame_data=parse.frame_data,
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=parse.prompt,
            subject="Core reason LLM task",
            control=context.control,
        )
        if isinstance(payload, ActionResult):
            return payload
        return _success(execution, payload)


class CoreAnswerActionExecutor:
    """Executor for the final answer action with read-only reference support."""

    def __init__(
        self,
        *,
        llm_action: LLMActionTaskRunner,
        reference_resolvers: Sequence[PromptReferenceResolver] = (),
    ) -> None:
        self._llm_action = llm_action
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
            return _failed(
                execution,
                parse.model_feedback,
                reason=parse.failure_reason,
                frame_data=parse.frame_data,
            )
        payload = self._llm_action.run_json(
            execution=execution,
            prompt=parse.prompt,
            subject="Answer LLM task",
            control=context.control,
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


class _PromptArgumentBuilder:
    def __init__(
        self,
        *,
        reference_resolvers: Sequence[PromptReferenceResolver],
    ) -> None:
        self._reference_resolvers = tuple(reference_resolvers)

    def context_task_prompt(self, params: JsonObject) -> _PromptParse:
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
                        *self._parse_reference_links(reference_links),
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

    def answer_prompt(self, params: JsonObject) -> _PromptParse:
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
                        *self._parse_reference_links(reference_links),
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
                    f"llm_action requires non-empty '{key}'.",
                    reason=f"missing_{key}",
                )
            return ()
        if not isinstance(value, list):
            raise _PromptParameterError(
                f"llm_action '{key}' must be a list.",
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
                f"llm_action requires non-empty '{key}'.",
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
                f"llm_action '{key}' items must be objects.",
                reason=f"invalid_{key}_item",
                payload={"index": index},
            ) from exc
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise _PromptParameterError(
                f"llm_action '{key}' items require non-empty text.",
                reason=f"invalid_{key}_text",
                payload={"index": index},
            )
        label_value = item.get("label")
        if label_value is not None and (
            not isinstance(label_value, str) or not label_value
        ):
            raise _PromptParameterError(
                f"llm_action '{key}' label must be non-empty when provided.",
                reason=f"invalid_{key}_label",
                payload={"index": index},
            )
        label_suffix = label_value if isinstance(label_value, str) else str(index)
        return PromptBlock.from_text(
            f"task_prompt:{section}:{label_suffix}",
            f"# {heading}\n{text}",
        )

    def _parse_reference_links(self, value: object) -> tuple[PromptBlock, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise PromptReferenceError(
                "llm_action 'reference_links' must be a list when provided.",
                reason="invalid_reference_links",
            )
        blocks: list[PromptBlock] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, str) or not item:
                raise PromptReferenceError(
                    "llm_action 'reference_links' items must be non-empty strings.",
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
            resolved = resolver.resolve_reference(item)
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
    llm_action: LLMActionTaskRunner,
    reference_resolvers: Sequence[PromptReferenceResolver] = (),
) -> ActionEngineBuilder:
    """Register built-in core actions on an action builder."""

    return builder.register_executor(
        "core.reason",
        CoreReasonActionExecutor(
            llm_action=llm_action,
            reference_resolvers=reference_resolvers,
        ),
    ).register_executor(
        "core.answer",
        CoreAnswerActionExecutor(
            llm_action=llm_action,
            reference_resolvers=reference_resolvers,
        ),
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
