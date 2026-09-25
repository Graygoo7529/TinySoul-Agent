"""Generation-owned HTTP resources; pinned embedding sessions never switch routes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from uuid import uuid4
from enum import StrEnum
from time import monotonic

import httpx

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object
from .config import (
    ModelServicesSettings,
    ModelCapability,
    ServiceModel,
    ServiceProvider,
    ServiceProviderBinding,
)
from .protocol import (
    EmbeddingBatch,
    DecisionRequest,
    DecisionResult,
    ModelServiceError,
    ModelFailureKind,
    parse_decision_response,
)


class ModelCallStatus(StrEnum):
    STARTED = "started"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ModelCallEvent:
    call_id: str
    consumer: str
    provider: str
    model: str
    capability: ModelCapability
    status: ModelCallStatus
    target: str
    attempt: int = 1
    retry: int = 0
    elapsed_seconds: float = 0.0
    input_count: int | None = None
    dimensions: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    failure: ModelFailureKind | None = None
    detail: JsonObject | None = None


ModelObserver = Callable[[ModelCallEvent], None]


def notify(observer: ModelObserver | None, event: ModelCallEvent) -> None:
    if observer is not None:
        try:
            observer(event)
        except Exception:
            # Observation is an optional side channel, never model control flow.
            pass


class EmbeddingSession:
    """One fixed vector space for every document and query in an owner attempt."""

    def __init__(
        self,
        service: ModelServices,
        model: ServiceModel,
        provider: ServiceProvider,
        binding: ServiceProviderBinding,
        use: str,
        attempt: int,
    ) -> None:
        self._service, self._model, self._provider, self._binding = (
            service,
            model,
            provider,
            binding,
        )
        self._use, self._attempt = use, attempt

    @property
    def identity(self) -> str:
        raw = f"{self._model.id}|{self._provider.adapter}|{self._provider.id}|{self._provider.base_url}|{self._binding.model}|{self._model.dimensions}"
        return sha256(raw.encode()).hexdigest()

    @property
    def max_batch_size(self) -> int:
        return self._model.batch_size

    @property
    def dimensions(self) -> int:
        assert self._model.dimensions is not None
        return self._model.dimensions

    async def embed(
        self,
        texts: Sequence[str],
        *,
        consumer: str,
        observer: ModelObserver | None = None,
    ) -> EmbeddingBatch:
        if (
            not texts
            or len(texts) > self.max_batch_size
            or any(not text.strip() for text in texts)
        ):
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Invalid embedding input batch"
            )
        identity, started = uuid4().hex, monotonic()

        def event(
            status: ModelCallStatus,
            *,
            retry: int = 0,
            failure: ModelFailureKind | None = None,
        ):
            notify(
                observer,
                ModelCallEvent(
                    identity,
                    consumer,
                    self._provider.id,
                    self._binding.model,
                    ModelCapability.EMBEDDING,
                    status,
                    self._use,
                    self._attempt,
                    retry,
                    monotonic() - started,
                    len(texts),
                    self.dimensions,
                    failure=failure,
                ),
            )

        event(ModelCallStatus.STARTED)
        try:
            value = await self._service.request(
                self._provider,
                "embeddings",
                {
                    "model": self._binding.model,
                    "input": list(texts),
                    "dimensions": self._model.dimensions,
                },
                on_retry=lambda retry: event(ModelCallStatus.RETRY, retry=retry),
            )
            result = self._parse(value, len(texts))
        except asyncio.CancelledError:
            event(ModelCallStatus.CANCELLED)
            raise
        except ModelServiceError as exc:
            event(ModelCallStatus.FAILED, failure=exc.kind)
            raise
        event(ModelCallStatus.COMPLETED)
        return result

    def _parse(self, value: JsonObject, count: int) -> EmbeddingBatch:
        data = value.get("data")
        if not isinstance(data, list) or len(data) != count:
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Embedding response count is invalid"
            )
        vectors: dict[int, tuple[float, ...]] = {}
        for item in data:
            if (
                not isinstance(item, dict)
                or type(item.get("index")) is not int
                or not isinstance(item.get("embedding"), list)
            ):
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT, "Embedding response entry is invalid"
                )
            index, raw = item["index"], item["embedding"]
            assert isinstance(index, int) and isinstance(raw, list)
            if (
                index in vectors
                or not 0 <= index < count
                or len(raw) != self._model.dimensions
                or any(
                    isinstance(x, bool)
                    or not isinstance(x, (int, float))
                    or not isfinite(x)
                    for x in raw
                )
            ):
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT, "Embedding vector or identity is invalid"
                )
            vectors[index] = tuple(float(x) for x in raw if isinstance(x, (int, float)))
        assert self._model.dimensions is not None
        return EmbeddingBatch(
            self._binding.model,
            self._model.dimensions,
            tuple(vectors[i] for i in range(count)),
        )


class ModelServices:
    """Only transports and capability routing; no Context, retrieval or Runtime policy."""

    def __init__(
        self,
        settings: ModelServicesSettings,
        *,
        env: Mapping[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings, self._env, self._transport = settings, dict(env), transport
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._closed = False

    def embedding_sessions(self, use: str) -> tuple[EmbeddingSession, ...]:
        self._require_open()
        model, routes = self.settings.resolve(use, ModelCapability.EMBEDDING, self._env)
        return tuple(
            EmbeddingSession(self, model, provider, binding, use, index)
            for index, (provider, binding) in enumerate(routes, 1)
        )

    async def decide(
        self,
        use: str,
        request: DecisionRequest,
        *,
        consumer: str,
        observer: ModelObserver | None = None,
    ) -> DecisionResult:
        model, routes = self.settings.resolve(
            use, ModelCapability.STRUCTURED_DECISION, self._env
        )
        last: ModelServiceError | None = None
        call_id = uuid4().hex
        for attempt, (provider, binding) in enumerate(routes, 1):
            started = monotonic()

            def event(
                status: ModelCallStatus,
                *,
                retry: int = 0,
                failure: ModelFailureKind | None = None,
                result: DecisionResult | None = None,
                detail: JsonObject | None = None,
            ):
                notify(
                    observer,
                    ModelCallEvent(
                        call_id,
                        consumer,
                        provider.id,
                        result.model if result else binding.model,
                        model.kind,
                        status,
                        use,
                        attempt,
                        retry,
                        monotonic() - started,
                        len(request.questions),
                        input_tokens=result.input_tokens if result else None,
                        output_tokens=result.output_tokens if result else None,
                        failure=failure,
                        detail=detail,
                    ),
                )

            payload: JsonObject = {
                "model": binding.model,
                "state": request.state,
                "questions": {
                    question.id: question.to_json() for question in request.questions
                },
            }
            event(ModelCallStatus.STARTED, detail=payload)
            try:
                value = await self.request(
                    provider,
                    "systemone",
                    payload,
                    on_retry=lambda retry: event(ModelCallStatus.RETRY, retry=retry),
                )
                try:
                    result = parse_decision_response(value, request)
                except ModelServiceError as exc:
                    raise ModelServiceError(
                        ModelFailureKind.OUTPUT,
                        "Decision response violates the output protocol",
                    ) from exc
            except asyncio.CancelledError:
                event(ModelCallStatus.CANCELLED)
                raise
            except ModelServiceError as exc:
                event(ModelCallStatus.FAILED, failure=exc.kind)
                if not exc.recoverable:
                    raise
                last = exc
                continue
            event(ModelCallStatus.COMPLETED, result=result, detail=value)
            return result
        assert last is not None
        raise last

    async def request(
        self,
        provider: ServiceProvider,
        endpoint: str,
        payload: JsonObject,
        *,
        on_retry: Callable[[int], None] | None = None,
    ) -> JsonObject:
        self._require_open()
        if provider.id not in self._clients:
            self._clients[provider.id] = httpx.AsyncClient(
                base_url=provider.base_url.rstrip("/") + "/",
                timeout=provider.timeout_seconds,
                headers={"Authorization": f"Bearer {self._env[provider.api_key_env]}"},
                transport=self._transport,
                proxy=provider.proxy,
            )
        client = self._clients[provider.id]
        for attempt in range(provider.max_retries + 1):
            if attempt:
                if on_retry:
                    on_retry(attempt)
                await asyncio.sleep(min(0.25 * 2 ** (attempt - 1), 2))
            try:
                response = await client.post(endpoint, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < provider.max_retries:
                    continue
                raise ModelServiceError(
                    ModelFailureKind.UNAVAILABLE, "Model transport unavailable"
                ) from exc
            if response.status_code in {408, 429, 500, 502, 503, 504, 529}:
                if attempt < provider.max_retries:
                    continue
                raise ModelServiceError(
                    ModelFailureKind.UNAVAILABLE,
                    "Model provider temporarily unavailable",
                )
            if response.status_code in {401, 403}:
                raise ModelServiceError(
                    ModelFailureKind.AUTHENTICATION,
                    "Model provider rejected authentication",
                )
            if response.status_code == 413:
                raise ModelServiceError(
                    ModelFailureKind.CAPACITY, "Model input exceeds provider capacity"
                )
            if not response.is_success:
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT, "Model provider rejected request"
                )
            try:
                return to_json_object(response.json())
            except (ValueError, JsonTypeError) as exc:
                raise ModelServiceError(
                    ModelFailureKind.CONTRACT, "Model response is not a JSON object"
                ) from exc
        raise ModelServiceError(ModelFailureKind.UNAVAILABLE, "Model attempt exhausted")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        clients, self._clients = tuple(self._clients.values()), {}
        results = await asyncio.gather(
            *(client.aclose() for client in clients), return_exceptions=True
        )
        if any(isinstance(result, BaseException) for result in results):
            raise ModelServiceError(
                ModelFailureKind.UNAVAILABLE, "Model transport cleanup failed"
            )

    def _require_open(self) -> None:
        if self._closed:
            raise ModelServiceError(
                ModelFailureKind.CONTRACT, "Model services generation is closed"
            )
