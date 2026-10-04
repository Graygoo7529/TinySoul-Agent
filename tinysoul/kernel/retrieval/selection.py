"""Candidate-specific LLM/JEV inputs and strict rank/select interpretation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from tinysoul.prompts.kernel import retrieval as prompt_text
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, JsonValue
from tinysoul.infra.model_services import ModelServices
from tinysoul.infra.model_services.protocol import (
    DecisionQuestion,
    DecisionRequest,
    ModelFailureKind,
    ModelServiceError,
    QuestionKind,
)
from tinysoul.infra.model_services.service import ModelCallEvent
from tinysoul.kernel.action.models import ModelImplementation, ModelUseRegistry
from tinysoul.llm.errors import LLMInvocationFailure

if TYPE_CHECKING:
    from tinysoul.kernel.context.prompts import PromptGuidance
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    JsonPart,
    MessageOrigin,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
    TaskCancellation,
)
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    JsonAnswer,
    TaskResult,
    TaskResultStatus,
)
from tinysoul.llm.protocol.tools import ToolUse
from tinysoul.runtime import RunScope

from .contracts import (
    EvidenceKind,
    ModelEvaluation,
    OperationKind,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
)
from .disclosure import project_candidate
from .engine import VectorSource, embedding_rank


class CandidateSelector:
    """One configured implementation per operation, without cross-kind fallback."""

    def __init__(
        self,
        *,
        models: ModelUseRegistry,
        invoke: Callable[[TaskCall], Awaitable[TaskResult]],
        services: ModelServices,
    ) -> None:
        self.models, self._invoke, self._services = models, invoke, services

    async def apply(
        self,
        *,
        consumer: str,
        query: str,
        candidates: tuple[SearchCandidate, ...],
        operation: OperationKind,
        context: MessageStack | None = None,
        guidance: tuple[PromptGuidance, ...] = (),
        scope: RunScope | None = None,
        cancellation: TaskCancellation | None = None,
        embedding: VectorSource | None = None,
        input_max_chars: int = 64_000,
        observer: Callable[[ModelCallEvent], None] | None = None,
        observe_task: Callable[[str], None] | None = None,
    ) -> tuple[SearchCandidate, ...]:
        if operation not in {OperationKind.RERANK, OperationKind.SELECT}:
            raise ConfigError(
                "Candidate selector requires rank or select", key=consumer
            )
        binding = self.models.binding(consumer)
        expected_operation = operation.value
        if self.models.descriptor(consumer).operation.value != expected_operation:
            raise ConfigError(
                "Consumer does not implement the requested operation", key=consumer
            )
        if cancellation:
            cancellation.check()
        if not candidates:
            return ()
        if binding.implementation is ModelImplementation.EMBEDDING_SIMILARITY:
            if context is not None or not query.strip() or embedding is None:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.INVALID_SIMILARITY_INPUT,
                )
            try:
                if (
                    len(query)
                    + sum(
                        len(unit.text)
                        for item in candidates
                        for unit in item.content_units
                    )
                    > input_max_chars
                ):
                    raise SearchFailure(
                        SearchFailureKind.SCOPE_REQUIRED,
                        prompt_text.SIMILARITY_INPUT_EXCEEDS_ITS_BUDGET_NARROW_SCOPE,
                    )
                ranked = await embedding_rank(
                    embedding, query, candidates, consumer=consumer, observer=observer
                )
                original = {item.ref: item for item in candidates}
                return tuple(
                    replace(
                        original[item.ref],
                        evaluation=ModelEvaluation(
                            operation,
                            item.content_coverage,
                            tuple(
                                hit
                                for hit in item.evidence[
                                    len(original[item.ref].evidence) :
                                ]
                            ),
                            item.score,
                            item.score_kind,
                        ),
                    )
                    for item in ranked
                )
            except ModelServiceError as exc:
                if not exc.recoverable:
                    raise
                raise SearchFailure(
                    SearchFailureKind.OPERATION_FAILED,
                    prompt_text.SIMILARITY_RANKING_IS_TEMPORARILY_UNAVAILABLE,
                ) from exc
        prepared = tuple(project_candidate(item, 4_000) for item in candidates)
        state: JsonObject = {
            "query": query,
            "candidates": [
                {
                    "id": f"c{index}",
                    "ref": item.ref,
                    "title": item.title,
                    "content_units": [
                        {"id": f"u{part_index}", **part.to_json()}
                        for part_index, part in enumerate(prepared[index].fragments)
                    ],
                    "attributes": item.attributes,
                    "content_coverage": prepared[index].coverage.value,
                }
                for index, item in enumerate(candidates)
            ],
            "guidance": [item.text for item in guidance],
        }
        if binding.implementation is ModelImplementation.STRUCTURED_DECISION:
            if context is not None:
                state["context"] = context_state(context)
            assert binding.use is not None
            levels = prompt_text.RELEVANCE_LEVELS
            request = DecisionRequest(
                state,
                tuple(
                    DecisionQuestion(
                        f"c{index}",
                        QuestionKind.SCORE,
                        prompt_text.relevance_question(index=index),
                        levels,
                    )
                    for index in range(len(candidates))
                ),
            )
            if (
                len(
                    json.dumps(
                        {
                            "state": state,
                            "questions": [
                                question.to_json() for question in request.questions
                            ],
                        },
                        ensure_ascii=False,
                    )
                )
                > input_max_chars
            ):
                raise SearchFailure(
                    SearchFailureKind.SCOPE_REQUIRED,
                    prompt_text.DECISION_INPUT_EXCEEDS_ITS_BUDGET_NARROW_SCOPE,
                )
            try:
                result = await self._services.decide(
                    binding.use, request, consumer=consumer, observer=observer
                )
            except ModelServiceError as exc:
                if exc.kind is ModelFailureKind.CAPACITY:
                    raise SearchFailure(
                        SearchFailureKind.SCOPE_REQUIRED,
                        prompt_text.DECISION_CAPACITY_EXCEEDED,
                    ) from exc
                if exc.kind is ModelFailureKind.OUTPUT:
                    raise SearchFailure(
                        SearchFailureKind.OPERATION_FAILED,
                        prompt_text.INVALID_DECISION_OUTPUT,
                    ) from exc
                if not exc.recoverable:
                    raise
                raise SearchFailure(
                    SearchFailureKind.OPERATION_FAILED,
                    prompt_text.DECISION_MODEL_IS_TEMPORARILY_UNAVAILABLE,
                ) from exc
            if cancellation:
                cancellation.check()
            scores = {answer.id: float(answer.value) for answer in result.answers}
            ordered = list(enumerate(candidates))
            if operation is OperationKind.RERANK:
                ordered.sort(key=lambda pair: -scores[f"c{pair[0]}"])
            return tuple(
                replace(
                    candidate,
                    evaluation=ModelEvaluation(
                        operation,
                        prepared[index].coverage,
                        score_kind="jev_relevance",
                        score=scores[f"c{index}"],
                    ),
                )
                for index, candidate in ordered
                if operation is OperationKind.RERANK
                or scores[f"c{index}"] >= binding.relevance_threshold
            )
        assert binding.task_profile is not None
        instruction = (
            prompt_text.RERANK_INSTRUCTION
            if operation is OperationKind.RERANK
            else prompt_text.SELECT_INSTRUCTION
        )
        prompt = UserMessage.from_json(
            {
                "task": instruction + prompt_text.SELECTION_OUTPUT_REQUIREMENTS,
                "input": state,
            },
            label="retrieval:selection",
        )
        messages = context or MessageStack()
        messages = messages.append(
            prompt,
            origin=MessageOrigin(
                "retrieval:selection",
                "retrieval",
                "task_prompt",
                "state",
                (len(messages.messages),),
                tuple(item.reference for item in guidance),
            ),
        )
        if (
            len(json.dumps(context_state(messages), ensure_ascii=False))
            > input_max_chars
        ):
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                prompt_text.SELECTION_INPUT_BUDGET_EXCEEDED,
            )
        call = TaskCall(
            profile=binding.task_profile,
            messages=messages,
            consumer=consumer,
            scope=scope or RunScope(),
            cancellation=cancellation,
            settings=CallSettings(
                answer_format=AnswerFormat.JSON_OBJECT,
                tool_use=ToolUse.DISABLED,
                max_output_tokens=binding.max_output_tokens,
            ),
            context_overflow_policy=ModelContextOverflowPolicy.RETURN_FAILURE,
        )
        if observe_task is not None:
            observe_task(call.task_id)
        try:
            result = await self._invoke(call)
        except LLMInvocationFailure as exc:
            if exc.kind in {
                LLMFailureKind.MODEL_CONTEXT_PRESSURE,
                LLMFailureKind.MODEL_CONTEXT_LIMIT_REACHED,
            }:
                raise SearchFailure(
                    SearchFailureKind.SCOPE_REQUIRED,
                    prompt_text.SELECTION_CAPACITY_EXCEEDED,
                ) from exc
            if not exc.recoverable:
                raise
            raise SearchFailure(
                SearchFailureKind.OPERATION_FAILED,
                prompt_text.SELECTION_MODEL_IS_TEMPORARILY_UNAVAILABLE,
            ) from exc
        if cancellation:
            cancellation.check()
        if result.status is TaskResultStatus.FAILURE:
            if (
                result.failure is not None
                and result.failure.reason.value == "input_capacity"
            ):
                raise SearchFailure(
                    SearchFailureKind.SCOPE_REQUIRED,
                    prompt_text.SELECTION_CAPACITY_EXCEEDED,
                )
            raise SearchFailure(
                SearchFailureKind.OPERATION_FAILED,
                prompt_text.INVALID_SELECTION_OUTPUT,
            )
        items = (
            result.answer.value.get("items")
            if isinstance(result.answer, JsonAnswer)
            else None
        )
        known = {
            f"c{index}": (candidate, preview)
            for index, (candidate, preview) in enumerate(
                zip(candidates, prepared, strict=True)
            )
        }
        if not isinstance(items, list):
            raise SearchFailure(
                SearchFailureKind.OPERATION_FAILED,
                prompt_text.SELECTION_RETURNED_UNKNOWN_CANDIDATE_IDENTITIES,
            )
        selected: dict[str, SearchCandidate] = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {"id", "basis_ids"}:
                raise SearchFailure(
                    SearchFailureKind.OPERATION_FAILED,
                    prompt_text.SELECTION_REQUIRES_CANDIDATE_AND_BASIS_IDENTITIES,
                )
            key, basis_ids = item["id"], item["basis_ids"]
            if (
                not isinstance(key, str)
                or key not in known
                or key in selected
                or not isinstance(basis_ids, list)
            ):
                raise SearchFailure(
                    SearchFailureKind.OPERATION_FAILED,
                    prompt_text.INVALID_SELECTION_IDENTITIES,
                )
            candidate, preview = known[key]
            fragments = {
                f"u{index}": part for index, part in enumerate(preview.fragments)
            }
            if any(
                not isinstance(identity, str) or identity not in fragments
                for identity in basis_ids
            ):
                raise SearchFailure(
                    SearchFailureKind.OPERATION_FAILED,
                    prompt_text.SELECTION_BASIS_OUTSIDE_CONTENT,
                )
            ids = tuple(identity for identity in basis_ids if isinstance(identity, str))
            if len(set(ids)) != len(ids):
                raise SearchFailure(
                    SearchFailureKind.OPERATION_FAILED,
                    prompt_text.SELECTION_RETURNED_DUPLICATE_BASIS_IDENTITIES,
                )
            basis = tuple(
                SearchEvidence(
                    fragments[identity].unit.id,
                    EvidenceKind.MODEL,
                    fragments[identity].start,
                    fragments[identity].end,
                )
                for identity in ids
            )
            selected[key] = replace(
                candidate,
                evaluation=ModelEvaluation(operation, preview.coverage, basis),
            )
        if operation is OperationKind.RERANK and set(selected) != set(known):
            raise SearchFailure(
                SearchFailureKind.OPERATION_FAILED,
                prompt_text.INVALID_RANKING_IDENTITIES,
            )
        return (
            tuple(selected.values())
            if operation is OperationKind.RERANK
            else tuple(selected[key] for key in known if key in selected)
        )


def context_state(messages: MessageStack) -> JsonObject:
    """Explicit text/JSON view for a text-only selector; never observation serialization."""
    result: list[JsonValue] = []
    for message in messages.messages:
        parts: list[JsonValue] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                parts.append({"text": part.text})
            elif isinstance(part, JsonPart):
                parts.append({"json": part.value})
            else:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.NON_TEXT_CONTEXT_UNSUPPORTED,
                )
        role = (
            "system"
            if isinstance(message, SystemMessage)
            else "user"
            if isinstance(message, UserMessage)
            else "assistant"
            if isinstance(message, AssistantMessage)
            else "tool"
        )
        entry: JsonObject = {"role": role, "label": message.label, "parts": parts}
        if isinstance(message, ToolResultMessage):
            entry.update(
                {
                    "call_id": message.call_id,
                    "tool_name": message.tool_name,
                    "status": message.status.value,
                }
            )
        if isinstance(message, AssistantMessage) and message.tool_calls:
            entry["tool_calls"] = [
                {"call_id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ]
        result.append(entry)
    return {"messages": result}
