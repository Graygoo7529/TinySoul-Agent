"""Source-owned query sessions share finite operations, not persistent resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import uuid4

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.json import JsonObject
from tinysoul.infra.model_services.protocol import ModelServiceError
from tinysoul.infra.model_services.service import ModelCallEvent
from tinysoul.infra.references import ReferenceError
from tinysoul.llm.protocol.messages import MessageStack
from tinysoul.llm.protocol.requests import TaskCancellation
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    Signal,
    emit_observation,
    observation_enabled,
)

from .contracts import (
    AttributeFilters,
    CandidateSet,
    FilterStep,
    ModelStep,
    QueryChannel,
    QuerySource,
    ResultSource,
    RetrievalRequest,
    SearchCandidate,
    SearchContext,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
    TextQuery,
)
from .engine import (
    SearchEngine,
    SearchViews,
    VectorSource,
    deduplicate,
    embedding_rank,
    fuse,
    lexical_rank,
    snapshot_size,
)
from .policy import RetrievalPolicy
from .selection import CandidateSelector

if TYPE_CHECKING:
    from tinysoul.kernel.context.prompts import PromptGuidance
    from tinysoul.kernel.loop.lifecycle.preparation import TurnPreparationRequest


@dataclass(frozen=True)
class SearchCorpus:
    candidates: tuple[SearchCandidate, ...]
    query: str
    scanned: int
    complete: bool = True


@dataclass(frozen=True)
class SelectionInput:
    context: MessageStack | None = None
    guidance: tuple[PromptGuidance, ...] = ()
    scope: RunScope | None = None
    cancellation: TaskCancellation | None = None


class SearchSession:
    """A bounded query view tied to an explicit service or Turn instance."""

    def __init__(
        self,
        *,
        action_id: str,
        retrieval_policies: tuple[RetrievalPolicy, ...] = (),
        source: Callable[[RetrievalRequest], Awaitable[SearchCorpus | CandidateSet]],
        selector: CandidateSelector | None = None,
        embedding: VectorSource | None = None,
        observations: ObservationEmitter | None = None,
        filters: AttributeFilters = AttributeFilters(),
        lexical: Callable[
            [QuerySource, str, tuple[SearchCandidate, ...]], tuple[SearchCandidate, ...]
        ] = lexical_rank,
    ) -> None:
        self.action_id = action_id
        self.retrieval_policies = tuple(
            item for item in retrieval_policies if item.action_id == action_id
        )
        self._source, self._selector = source, selector
        self._engine = SearchEngine(views=SearchViews(), embedding=embedding)
        self._closed = False
        self._turn_id: str | None = None
        self._observations = observations
        self._filters = filters
        self._lexical = lexical

    async def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        if self._turn_id != request.turn_id:
            self._engine.views.close()
            self._turn_id = request.turn_id
            self._closed = False
        return ()

    async def search(
        self,
        request: RetrievalRequest | str,
        *,
        inputs: SelectionInput = SelectionInput(),
    ) -> SearchPage:
        if self._closed:
            raise SearchFailure(
                SearchFailureKind.VIEW_EXPIRED,
                "Search scope has closed; start a new query scope",
            )
        if isinstance(request, str):
            return self._engine.views.resume(request)
        return await self._search_retrieval(request, inputs=inputs)

    async def _search_retrieval(
        self, request: RetrievalRequest, *, inputs: SelectionInput
    ) -> SearchPage:
        if self._closed:
            raise SearchFailure(
                SearchFailureKind.VIEW_EXPIRED,
                "Search scope has closed; start a new query scope",
            )
        policy = next(
            (
                item
                for item in self.retrieval_policies
                if item.action_id == self.action_id
            ),
            None,
        )
        if policy is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "This action has no retrieval policy"
            )
        policy.validate_request(request)
        filters = policy.capability.filters if policy.capability else self._filters
        for where in [
            getattr(request.source, "where", {}),
            *(step.where for step in request.steps if isinstance(step, FilterStep)),
        ]:
            filters.parse(where)
        current_steps = [
            step
            for step in request.steps
            if isinstance(step, ModelStep) and step.context is SearchContext.CURRENT
        ]
        if current_steps and inputs.context is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Current Context is unavailable; use context=none",
            )
        if inputs.cancellation:
            inputs.cancellation.check()
        if isinstance(request.source, ResultSource):
            corpus_value = self._engine.views.result(request.source.result_ref)
            corpus_value = replace(
                corpus_value,
                candidates=tuple(
                    item
                    for item in corpus_value.candidates
                    if item.ref not in request.exclude_refs
                ),
            )
        else:
            try:
                corpus_value = await self._source(request)
            except ReferenceError as exc:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "Search source reference is invalid or unreadable",
                ) from exc
        if isinstance(corpus_value, SearchCorpus):
            corpus = CandidateSet(
                corpus_value.candidates, corpus_value.scanned, corpus_value.complete
            )
        else:
            corpus = corpus_value
        corpus = replace(corpus, candidates=deduplicate(corpus.candidates))
        if snapshot_size(corpus.candidates) > policy.snapshot_max_chars:
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                "Source content snapshot exceeds its budget; narrow the scope",
            )
        if not corpus.complete:
            raise SearchFailure(
                SearchFailureKind.SCOPE_REQUIRED,
                "Source scope exceeds its read budget; narrow the scope",
            )
        search_id = uuid4().hex

        def observe(event: ModelCallEvent, step_index: int | None = None) -> None:
            if self._observations is None:
                return
            payload: JsonObject = {
                "search_id": search_id,
                "call_id": event.call_id,
                "consumer": event.consumer,
                "implementation": event.capability.value,
                "target": event.target,
                "provider": event.provider,
                "model": event.model,
                "attempt": event.attempt,
                "retry": event.retry,
                "elapsed_seconds": event.elapsed_seconds,
                "input_count": event.input_count,
                "dimensions": event.dimensions,
                "usage": {
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                },
                "failure": event.failure.value if event.failure else None,
            }
            payload.update(
                {
                    "step_index": step_index,
                    "phase": "source" if step_index is None else "step",
                }
            )
            emit_observation(
                self._observations,
                ObservationEvent(
                    name=f"model.call.{event.status.value}",
                    source="retrieval.model",
                    level=ObservationLevel.VERBOSE,
                    scope=inputs.scope or RunScope(),
                    message=f"Model call {event.status.value}.",
                    payload=payload,
                ),
            )
            if event.detail is not None and observation_enabled(
                self._observations, ObservationLevel.MODEL
            ):
                emit_observation(
                    self._observations,
                    ObservationEvent(
                        name="model.call.detail",
                        source="retrieval.model",
                        level=ObservationLevel.MODEL,
                        scope=inputs.scope or RunScope(),
                        message="Prepared model input or result.",
                        payload={**payload, "detail": event.detail},
                    ),
                )

        def observe_step(stats: JsonObject) -> None:
            if self._observations is not None:
                emit_observation(
                    self._observations,
                    ObservationEvent(
                        name="retrieval.step.completed",
                        source="retrieval",
                        level=ObservationLevel.VERBOSE,
                        scope=inputs.scope or RunScope(),
                        message="Search operation completed.",
                        payload={
                            "search_id": search_id,
                            "action": self.action_id,
                            **stats,
                        },
                    ),
                )

        if isinstance(request.source, QuerySource):
            corpus = await self._query_candidates(
                request.source,
                corpus,
                policy,
                inputs=inputs,
                query=corpus_value.query
                if isinstance(corpus_value, SearchCorpus)
                else None,
                observer=observe,
            )

        async def apply_operation(
            index: int, step: ModelStep, candidates: tuple[SearchCandidate, ...]
        ) -> tuple[SearchCandidate, ...]:
            if self._selector is None:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "The query scope has no configured selector",
                    step=step.op.value,
                )
            operation_policy = policy.operation(step.op)

            def observe_task(task_id: str) -> None:
                if self._observations is not None:
                    emit_observation(
                        self._observations,
                        ObservationEvent(
                            name="retrieval.model.invoked",
                            source="retrieval",
                            level=ObservationLevel.VERBOSE,
                            scope=inputs.scope or RunScope(),
                            message="Search model task invoked.",
                            payload={
                                "search_id": search_id,
                                "step_index": index,
                                "op": step.op.value,
                                "task_id": task_id,
                                "consumer": f"{self.action_id}.{step.op.value}",
                            },
                        ),
                    )

            return await self._selector.apply(
                consumer=f"{self.action_id}.{step.op.value}",
                query=step.criterion,
                operation=step.op,
                candidates=candidates,
                context=inputs.context
                if step.context is SearchContext.CURRENT
                else None,
                guidance=inputs.guidance,
                scope=inputs.scope,
                cancellation=inputs.cancellation,
                embedding=self._engine.embedding,
                input_max_chars=operation_policy.input_max_chars,
                observer=lambda event: observe(event, index),
                observe_task=observe_task,
            )

        page_chars = request.page_max_chars or policy.page_max_chars
        return await self._engine.compose(
            request,
            corpus=corpus,
            page_max_chars=min(page_chars, policy.page_max_chars),
            snapshot_max_chars=policy.snapshot_max_chars,
            apply_operation=apply_operation,
            observe_step=observe_step,
            filters=filters,
        )

    async def _query_candidates(
        self,
        source: QuerySource,
        corpus: CandidateSet,
        policy: RetrievalPolicy,
        *,
        inputs: SelectionInput,
        query: str | None = None,
        observer: Callable[[ModelCallEvent], None] | None = None,
    ) -> CandidateSet:
        # The source query is the request's semantic input.  An owner may
        # return a normalized query in SearchCorpus, but an empty corpus
        # query must never erase the explicit request query.
        if isinstance(source.query, TextQuery):
            query = source.query.text
        elif query is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Source owner did not resolve the document query",
            )
        if policy.capability and policy.capability.lexical_syntax and not source.regex:
            source = replace(source, literal=True)
        channels = policy.query_channels
        rankings: list[tuple[SearchCandidate, ...]] = []
        missing = list(corpus.missing_stages)
        stages = list(corpus.stages)
        if QueryChannel.LEXICAL in channels:
            lexical = self._lexical(source, query, corpus.candidates)
            rankings.append(lexical)
            stages.append(QueryChannel.LEXICAL.value)
        if QueryChannel.EMBEDDING in channels:
            if self._engine.embedding is None:
                missing.append("embedding:unavailable")
            else:
                try:
                    ranked = await embedding_rank(
                        self._engine.embedding,
                        query,
                        corpus.candidates,
                        consumer=f"{self.action_id}.query.embedding",
                        observer=observer,
                    )
                except ModelServiceError as exc:
                    if not exc.recoverable:
                        raise
                    missing.append("embedding:unavailable")
                else:
                    rankings.append(ranked)
                    stages.append(QueryChannel.EMBEDDING.value)
        if not rankings:
            raise SearchFailure(
                SearchFailureKind.SOURCE_UNAVAILABLE,
                "Every configured query channel was unavailable",
            )
        return CandidateSet(
            fuse(rankings),
            corpus.scanned,
            corpus.complete,
            tuple(stages),
            tuple(missing),
        )

    def close(self) -> None:
        self._closed = True
        self._engine.views.close()

    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        self.close()
        return ()
