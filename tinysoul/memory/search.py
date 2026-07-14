"""Bounded search over complete date-scoped Memory documents."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
from unicodedata import normalize

from tinysoul.infra.json import JsonObject
from tinysoul.llm import (
    AnswerFormat,
    CallSettings,
    JsonAnswer,
    MessageStack,
    SystemMessage,
    TaskCall,
    TaskProfile,
    TaskResult,
    TaskResultStatus,
    ToolUse,
    UserMessage,
)
from tinysoul.runtime import RunScope

from .config import MemorySearchSettings
from .errors import MemoryContractError
from .links import MemoryLink
from .store import MemoryStore


_WORD_PATTERN = re.compile(r"[\w-]+", re.UNICODE)


@dataclass(frozen=True)
class MemorySearchCandidate:
    link: str
    day: str
    summary: str
    digest: str
    score: int

    @property
    def candidate_id(self) -> str:
        return self.link


@dataclass(frozen=True)
class MemorySearchRequest:
    query: str
    top_k: int
    candidates: tuple[MemorySearchCandidate, ...]


class MemorySearchReranker(Protocol):
    def rerank(
        self,
        request: MemorySearchRequest,
        *,
        scope: RunScope,
    ) -> tuple[str, ...] | None: ...


@dataclass(frozen=True)
class MemorySearchItem:
    link: str
    day: str
    summary: str
    digest: str
    score: int

    def to_json(self) -> JsonObject:
        return {
            "link": self.link,
            "date": self.day,
            "summary": self.summary,
            "digest": self.digest,
            "score": self.score,
        }


@dataclass(frozen=True)
class MemorySearchResult:
    query: str
    top_k: int
    candidate_count: int
    reranked: bool
    items: tuple[MemorySearchItem, ...]


class MemorySearchService:
    def __init__(self, *, store: MemoryStore, settings: MemorySearchSettings) -> None:
        if not isinstance(store, MemoryStore):
            raise MemoryContractError("Memory search store is invalid")
        if not isinstance(settings, MemorySearchSettings):
            raise MemoryContractError("Memory search settings are invalid")
        self._store = store
        self._settings = settings

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        reranker: MemorySearchReranker | None = None,
        scope: RunScope | None = None,
    ) -> MemorySearchResult:
        normalized_query = _normalize(query)
        if not normalized_query:
            raise MemoryContractError("Memory search query must be non-empty")
        if len(query) > self._store.max_document_chars:
            raise MemoryContractError("Memory search query exceeds its size limit")
        limit = self._settings.default_top_k if top_k is None else top_k
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self._settings.max_top_k
        ):
            raise MemoryContractError(
                f"Memory search top_k must be between 1 and {self._settings.max_top_k}"
            )
        candidates = self._candidates(normalized_query)
        selected = candidates[:limit]
        reranked = False
        if candidates and reranker is not None:
            if scope is None:
                raise MemoryContractError("Memory search reranking requires a scope")
            ids = reranker.rerank(
                MemorySearchRequest(
                    query=query.strip(),
                    top_k=limit,
                    candidates=candidates,
                ),
                scope=scope,
            )
            validated = _validated_rerank(
                ids,
                candidates=candidates,
                top_k=limit,
            )
            if validated is not None:
                by_id = {item.candidate_id: item for item in candidates}
                selected = tuple(by_id[item_id] for item_id in validated)
                reranked = True
        return MemorySearchResult(
            query=query.strip(),
            top_k=limit,
            candidate_count=len(candidates),
            reranked=reranked,
            items=tuple(
                MemorySearchItem(
                    link=item.link,
                    day=item.day,
                    summary=item.summary,
                    digest=item.digest,
                    score=item.score,
                )
                for item in selected
            ),
        )

    def _candidates(self, query: str) -> tuple[MemorySearchCandidate, ...]:
        best: list[MemorySearchCandidate] = []
        for link in self._store.iter_links():
            document = self._store.read(link)
            best.append(
                MemorySearchCandidate(
                    link=str(link),
                    day=link.day.isoformat(),
                    summary=_summary(
                        document.text,
                        day=link.day.isoformat(),
                        max_chars=self._settings.summary_max_chars,
                    ),
                    digest=document.digest,
                    score=_score(query, link, document.text),
                )
            )
            best.sort(key=lambda item: (-item.score, item.link))
            if len(best) > self._settings.candidate_limit:
                del best[self._settings.candidate_limit :]
        return tuple(best)


class MemorySearchModelRunner(Protocol):
    def run(self, call: TaskCall) -> TaskResult: ...


class LLMMemorySearchReranker:
    def __init__(self, runner: MemorySearchModelRunner) -> None:
        self._runner = runner

    def rerank(
        self,
        request: MemorySearchRequest,
        *,
        scope: RunScope,
    ) -> tuple[str, ...] | None:
        result = self._runner.run(
            TaskCall(
                profile=TaskProfile.MEMORY_SEARCH,
                messages=MessageStack.of(
                    SystemMessage.from_text(
                        "Rank only the supplied single-day Memory candidates. "
                        "Do not invent candidate ids.",
                        label="memory_search_role",
                    ),
                    UserMessage.from_json(
                        {
                            "query": request.query,
                            "top_k": request.top_k,
                            "candidates": [
                                {
                                    "candidate_id": item.candidate_id,
                                    "link": item.link,
                                    "date": item.day,
                                    "summary": item.summary,
                                }
                                for item in request.candidates
                            ],
                        },
                        label="memory_search_candidates",
                    ),
                    UserMessage.from_text(
                        'Return exactly {"candidate_ids":["memory:YYYY-MM-DD"]}.',
                        label="memory_search_output",
                    ),
                ),
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                ),
                scope=scope,
            )
        )
        if result.status is TaskResultStatus.FAILURE or not isinstance(
            result.answer,
            JsonAnswer,
        ):
            return None
        value = result.answer.value
        if set(value) != {"candidate_ids"}:
            return None
        ids = value.get("candidate_ids")
        if not isinstance(ids, list) or any(
            not isinstance(item, str) for item in ids
        ):
            return None
        return tuple(item for item in ids if isinstance(item, str))


def _validated_rerank(
    ids: tuple[str, ...] | None,
    *,
    candidates: tuple[MemorySearchCandidate, ...],
    top_k: int,
) -> tuple[str, ...] | None:
    if ids is None or len(ids) > top_k or len(ids) != len(set(ids)):
        return None
    candidate_ids = {item.candidate_id for item in candidates}
    if any(item_id not in candidate_ids for item_id in ids):
        return None
    return ids


def _score(query: str, link: MemoryLink, body: str) -> int:
    day = link.day.isoformat()
    normalized = _normalize(f"{day} {body}")
    score = 5000 if query == day or query == str(link) else 0
    if query in normalized:
        score += 1000
    query_units = _units(query)
    if query_units:
        score += 500 * len(query_units.intersection(_units(normalized))) // len(
            query_units
        )
    return score


def _summary(value: str, *, day: str, max_chars: int) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if lines and lines[0] == f"# {day}":
        lines = lines[1:]
    return " ".join(lines)[:max_chars]


def _normalize(value: str) -> str:
    if not isinstance(value, str):
        raise MemoryContractError("Memory search query must be text")
    return " ".join(normalize("NFKC", value).casefold().split())


def _units(value: str) -> frozenset[str]:
    words = set(_WORD_PATTERN.findall(value))
    compact = "".join(character for character in value if character.isalnum())
    words.update(compact[index : index + 2] for index in range(len(compact) - 1))
    if len(compact) == 1:
        words.add(compact)
    return frozenset(words)
