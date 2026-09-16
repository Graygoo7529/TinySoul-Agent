"""Deletable semantic-search cache derived from Memory Markdown."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path

from tinysoul.infra import (
    EmbeddingClient,
    EmbeddingError,
    atomic_write_text,
    read_text_prefix,
)

from tinysoul.infra.concurrency import JoinedOperations

from .errors import MemoryContractError, MemoryIOError
from .links import MemoryLink


@dataclass(frozen=True)
class _CachedVector:
    digest: str
    vector: tuple[float, ...]


class MemoryEmbeddingIndex:
    """Persist document vectors while keeping Markdown as the only business fact."""

    def __init__(
        self,
        *,
        path: Path,
        client: EmbeddingClient,
        cache_max_chars: int,
        batch_size: int = 64,
    ) -> None:
        self._path = path
        self._client = client
        self._cache_max_chars = cache_max_chars
        self._batch_size = min(batch_size, client.max_batch_size)
        if self._batch_size <= 0:
            raise MemoryIOError("Memory embedding batch size is invalid")
        self._entries: dict[MemoryLink, _CachedVector] = {}
        self._dimensions = 0
        self._lock = asyncio.Lock()
        self._load()

    async def similarities(
        self,
        query: str,
        documents: Mapping[MemoryLink, str],
    ) -> Mapping[MemoryLink, float]:
        # One fixed set of embedding inputs and one cache generation per query.
        # A failed or cancelled refresh cannot install partial vectors.
        async with self._lock:
            try:
                await self._refresh(documents)
                usable = {
                    link: item for link, item in self._entries.items()
                    if link in documents
                    and item.digest == _text_digest(documents[link])
                    and len(item.vector) == self._dimensions
                }
                if not usable:
                    return {}
                batch = await self._client.embed((query,))
            except (EmbeddingError, MemoryIOError):
                return {}
            if batch.dimensions != self._dimensions:
                return {}
            return {
                link: _cosine(batch.vectors[0], item.vector)
                for link, item in usable.items()
            }

    async def _refresh(self, documents: Mapping[MemoryLink, str]) -> None:
        entries = dict(self._entries)
        pending = [
            (link, _text_digest(text), text)
            for link, text in documents.items()
            if link not in entries or entries[link].digest != _text_digest(text)
        ]
        if not pending:
            return
        dimensions = self._dimensions
        for start in range(0, len(pending), self._batch_size):
            chunk = pending[start : start + self._batch_size]
            batch = await self._client.embed(tuple(text for _, _, text in chunk))
            if dimensions and batch.dimensions != dimensions:
                raise EmbeddingError("Memory embedding dimensions changed")
            dimensions = batch.dimensions
            for (link, digest, _), vector in zip(chunk, batch.vectors, strict=True):
                entries[link] = _CachedVector(digest=digest, vector=vector)
        operations = JoinedOperations()
        await operations.run(lambda: self._write(entries, dimensions))
        self._entries = entries
        self._dimensions = dimensions
        operations.check_cancelled()

    def _load(self) -> None:
        if not self._path.is_file() or self._path.is_symlink():
            return
        try:
            read = read_text_prefix(self._path, max_chars=self._cache_max_chars)
            if read.truncated:
                return
            value = json.loads(read.text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 2
            or value.get("identity") != self._client.identity
        ):
            return
        dimensions = value.get("dimensions")
        entries = value.get("entries")
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
            return
        if not isinstance(entries, dict):
            return
        loaded: dict[MemoryLink, _CachedVector] = {}
        try:
            for raw_link, raw in entries.items():
                if not isinstance(raw_link, str) or not isinstance(raw, dict):
                    return
                digest = raw.get("digest")
                vector = raw.get("vector")
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    or not isinstance(vector, list)
                ):
                    return
                if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in vector):
                    return
                parsed = tuple(float(item) for item in vector)
                if len(parsed) != dimensions or any(
                    not math.isfinite(item) for item in parsed
                ):
                    return
                loaded[MemoryLink.parse(raw_link)] = _CachedVector(digest, parsed)
        except (TypeError, ValueError, MemoryContractError):
            return
        self._dimensions = dimensions
        self._entries = loaded

    def _write(self, entries: Mapping[MemoryLink, _CachedVector], dimensions: int) -> None:
        value = {
            "schema_version": 2,
            "identity": self._client.identity,
            "dimensions": dimensions,
            "entries": {
                str(link): {"digest": item.digest, "vector": list(item.vector)}
                for link, item in sorted(entries.items(), key=lambda pair: str(pair[0]))
            },
        }
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text) > self._cache_max_chars:
            raise EmbeddingError("Memory embedding cache exceeds configured size")
        try:
            atomic_write_text(self._path, text)
        except OSError as exc:
            raise MemoryIOError("Failed to write Memory embedding cache") from exc


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _text_digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
