"""Reusable vector math/cache mechanics; each source owner supplies its own cache path."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from math import isfinite, sqrt
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.concurrency import JoinedOperations
from .service import EmbeddingSession, ModelServices, ModelObserver
from .protocol import ModelServiceError, ModelFailureKind


class EmbeddingIndex:
    """Rebuildable vectors for one owner's explicitly supplied evidence collection."""

    def __init__(
        self,
        *,
        path: Path,
        services: ModelServices,
        use: str,
        max_chars: int = 16_000_000,
        extraction: str = "content-units-v2",
    ) -> None:
        self._path, self._services, self._use = path, services, use
        self._max_chars, self._extraction = max_chars, extraction
        self._lock = asyncio.Lock()

    async def similarities(
        self,
        query: str,
        documents: Mapping[str, str],
        *,
        consumer: str = "embedding",
        observer: ModelObserver | None = None,
    ) -> Mapping[str, float]:
        if not documents:
            return {}
        async with self._lock:
            last: ModelServiceError | None = None
            for session in self._services.embedding_sessions(self._use):
                try:
                    return await self._attempt(
                        session, query, documents, consumer=consumer, observer=observer
                    )
                except ModelServiceError as exc:
                    if not exc.recoverable:
                        raise
                    last = exc
            assert last is not None
            raise last

    async def _attempt(
        self,
        session: EmbeddingSession,
        query: str,
        documents: Mapping[str, str],
        *,
        consumer: str,
        observer: ModelObserver | None,
    ) -> Mapping[str, float]:
        identity = sha256(f"{session.identity}|{self._use}|{self._extraction}".encode()).hexdigest()
        cache_path = self._path / f"{identity}.json"
        operations = JoinedOperations()
        loaded = await operations.run(lambda: self._load(cache_path))
        # Cache text identities, independently of the candidate set of a call.
        # Discovery and reranking therefore share vectors without evicting each
        # other's scopes or introducing vectors from another provider space.
        cached = {digest: vector for digest, (stored_digest, vector) in loaded.items()
                  if digest == stored_digest and len(vector) == session.dimensions}
        texts = {_digest(text): text for text in documents.values()}
        pending = [(digest, text) for digest, text in texts.items() if digest not in cached]
        for start in range(0, len(pending), session.max_batch_size):
            chunk = pending[start : start + session.max_batch_size]
            batch = await session.embed(
                [text for _, text in chunk], consumer=consumer, observer=observer
            )
            cached.update(
                (digest, vector)
                for (digest, _), vector in zip(chunk, batch.vectors, strict=True)
            )
        # The query is always embedded in this same pinned session. A route
        # failure restarts the whole attempt with that route's independent cache.
        query_batch = await session.embed(
            (query,), consumer=consumer, observer=observer
        )
        dimension = query_batch.dimensions
        vectors = {ref: cached[_digest(text)] for ref, text in documents.items()}
        if any(len(vector) != dimension for vector in vectors.values()):
            raise ModelServiceError(
                ModelFailureKind.CONTRACT,
                "Cached vector dimensions do not match the selected model",
            )
        scores = {
            ref: cosine(query_batch.vectors[0], vector)
            for ref, vector in vectors.items()
        }
        for digest in texts:
            cached[digest] = cached.pop(digest)
        entries: dict[str, object] = {}
        used = 2
        for digest, vector in reversed(tuple(cached.items())):
            entry = {"digest": digest, "vector": vector}
            size = len(json.dumps({digest: entry}, separators=(",", ":")))
            if used + size > self._max_chars:
                continue
            entries[digest] = entry
            used += size
        encoded = json.dumps(dict(reversed(tuple(entries.items()))), separators=(",", ":"))
        await operations.run(lambda: self._write(cache_path, encoded))
        operations.check_cancelled()
        return scores

    def _load(self, path: Path) -> dict[str, tuple[str, tuple[float, ...]]]:
        if not path.is_file() or path.is_symlink():
            return {}
        try:
            with path.open(encoding="utf-8") as stream:
                text = stream.read(self._max_chars + 1)
            if len(text) > self._max_chars:
                return {}
            value = json.loads(text)
        except (OSError, UnicodeError, ValueError):
            return {}
        if not isinstance(value, dict):
            return {}
        result = {}
        for ref, entry in value.items():
            if not isinstance(ref, str) or not isinstance(entry, dict):
                return {}
            digest, vector = entry.get("digest"), entry.get("vector")
            if (
                not isinstance(digest, str)
                or not isinstance(vector, list)
                or not vector
                or any(
                    isinstance(x, bool)
                    or not isinstance(x, (int, float))
                    or not isfinite(x)
                    for x in vector
                )
            ):
                return {}
            result[ref] = (digest, tuple(float(x) for x in vector))
        return result

    @staticmethod
    def _write(path: Path, encoded: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, encoded)
        except OSError as exc:
            raise ModelServiceError(
                ModelFailureKind.STORAGE, "Derived vector cache cannot be written"
            ) from exc


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ModelServiceError(ModelFailureKind.CONTRACT, "Vector dimensions differ")
    denominator = sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return (
        sum(a * b for a, b in zip(left, right, strict=True)) / denominator
        if denominator
        else 0.0
    )


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
