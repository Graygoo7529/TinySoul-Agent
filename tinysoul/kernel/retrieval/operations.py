"""Source-owned query sessions share finite operations, not persistent resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tinysoul.llm.protocol.messages import MessageStack
from tinysoul.llm.protocol.requests import TaskCancellation
from tinysoul.runtime import RunScope, Signal
from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    emit_observation,
    observation_enabled,
)
from tinysoul.infra.model_services.service import ModelCallEvent
from tinysoul.infra.model_services.config import ModelCapability
from tinysoul.infra.json import JsonObject
from tinysoul.infra.concurrency import CleanupDiagnostic
from .contracts import (
    SearchCandidate,
    SearchContext,
    SearchFailure,
    SearchFailureKind,
    SearchPage,
    SearchRequest,
    SearchSemantic,
)
from .engine import SearchEngine, SearchViews, VectorSource
from .policy import SearchPolicy
from .selection import CandidateSelector

if TYPE_CHECKING:
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
    guidance: tuple[str, ...] = ()
    scope: RunScope | None = None
    cancellation: TaskCancellation | None = None


class SearchSession:
    """A bounded query view tied to an explicit service or Turn instance."""

    def __init__(
        self,
        *,
        action_id: str,
        policies: tuple[SearchPolicy, ...],
        source: Callable[[SearchRequest], Awaitable[SearchCorpus]],
        selector: CandidateSelector | None = None,
        embedding: VectorSource | None = None,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self.action_id = action_id
        self.policies = tuple(
            policy for policy in policies if policy.action_id == action_id
        )
        self._source, self._selector = source, selector
        self._engine = SearchEngine(views=SearchViews(), embedding=embedding)
        self._closed = False
        self._turn_id: str | None = None
        self._observations = observations

    async def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        if self._turn_id != request.turn_id:
            self._engine.views.close()
            self._turn_id = request.turn_id
            self._closed = False
        return ()

    async def search(
        self, request: SearchRequest | str, *, inputs: SelectionInput = SelectionInput()
    ) -> SearchPage:
        if self._closed:
            raise SearchFailure(
                SearchFailureKind.CONTINUATION_EXPIRED,
                "Search scope has closed; start a new query scope",
            )
        if isinstance(request, str):
            return self._engine.views.resume(request)
        policy = next(
            (item for item in self.policies if item.mode is request.mode), None
        )
        if policy is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "This source has no configured policy for the requested mode",
            )
        if request.options.context is SearchContext.CURRENT and inputs.context is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Current Context is unavailable in this query scope; use context=none",
            )
        if inputs.cancellation:
            inputs.cancellation.check()
        corpus = await self._source(request)

        def observe(event: ModelCallEvent) -> None:
            if self._observations is None:
                return
            payload: JsonObject = {
                "call_id": event.call_id,
                "consumer": event.consumer,
                "implementation": "structured_decision"
                if event.capability is ModelCapability.STRUCTURED_DECISION
                else "embedding_similarity",
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

        async def semantic(
            query: str,
            candidates: tuple[SearchCandidate, ...],
            operation: SearchSemantic,
        ) -> tuple[SearchCandidate, ...]:
            if self._selector is None:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "The query scope has no configured selector",
                )
            return await self._selector.apply(
                consumer=f"{self.action_id}.{operation.value}",
                query=query,
                candidates=candidates,
                operation=operation,
                context=inputs.context
                if request.options.context is SearchContext.CURRENT
                else None,
                guidance=inputs.guidance,
                scope=inputs.scope,
                cancellation=inputs.cancellation,
                embedding=self._engine.embedding,
                input_max_chars=policy.input_max_chars,
                observer=observe,
            )

        return await self._engine.search(
            request,
            policy=policy,
            candidates=corpus.candidates,
            query=corpus.query,
            scanned=corpus.scanned,
            source_complete=corpus.complete,
            semantic=semantic,
            observer=observe,
        )

    def close(self) -> None:
        self._closed = True
        self._engine.views.close()

    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        self.close()
        return ()
