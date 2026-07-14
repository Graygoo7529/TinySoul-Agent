"""Bounded search over the effective Agent Home top catalog."""

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

from .config import HomeSearchSettings
from .errors import AgentHomeContractError
from .links import HomeTopLink


SEARCHABLE_HOME_SPACES = frozenset({"what", "why", "how", "memory"})
_TITLE_MAX_CHARS = 160
_WORD_PATTERN = re.compile(r"[\w]+", flags=re.UNICODE)


@dataclass(frozen=True)
class HomeSearchDocument:
    """One bounded effective top document supplied by AgentHomeEngine."""

    link: HomeTopLink
    text_prefix: str
    truncated: bool
    digest: str

    def __post_init__(self) -> None:
        if self.link.space not in SEARCHABLE_HOME_SPACES:
            raise AgentHomeContractError(
                f"Home search document has a non-searchable space: {self.link}"
            )
        if not isinstance(self.text_prefix, str):
            raise AgentHomeContractError("Home search document prefix must be text")
        if not isinstance(self.truncated, bool):
            raise AgentHomeContractError("Home search truncated flag must be boolean")
        if not isinstance(self.digest, str) or not self.digest:
            raise AgentHomeContractError("Home search document digest must be non-empty")


@dataclass(frozen=True)
class HomeSearchEntry:
    """Metadata for one searchable effective top entry."""

    link: str
    space: str
    title: str
    summary: str
    digest: str
    searchable_prefix: str
    prefix_truncated: bool


@dataclass(frozen=True)
class HomeSearchCandidate:
    """One deterministic candidate and its stable lexical score."""

    entry: HomeSearchEntry
    score: int


@dataclass(frozen=True)
class HomeSearchRequest:
    """Validated rerank input restricted to deterministic candidates."""

    query: str
    top_k: int
    candidates: tuple[HomeSearchCandidate, ...]


class HomeSearchReranker(Protocol):
    """Optional semantic reranker for deterministic Home candidates."""

    def rerank(
        self,
        request: HomeSearchRequest,
        *,
        scope: RunScope,
    ) -> tuple[str, ...] | None: ...


@dataclass(frozen=True)
class HomeSearchItem:
    """Metadata-only action result item."""

    link: str
    space: str
    title: str
    summary: str
    digest: str
    score: int

    def to_json(self) -> JsonObject:
        return {
            "link": self.link,
            "space": self.space,
            "title": self.title,
            "summary": self.summary,
            "digest": self.digest,
            "score": self.score,
        }


@dataclass(frozen=True)
class HomeSearchResult:
    """One bounded top search result."""

    query: str
    top_k: int
    candidate_count: int
    reranked: bool
    items: tuple[HomeSearchItem, ...]


class HomeTopSearchService:
    """Build metadata, limit candidates, and apply an optional reranker."""

    def __init__(self, settings: HomeSearchSettings) -> None:
        if not isinstance(settings, HomeSearchSettings):
            raise AgentHomeContractError("Home search settings are invalid")
        self._settings = settings

    @property
    def prefix_max_chars(self) -> int:
        return self._settings.prefix_max_chars

    def search(
        self,
        *,
        query: str,
        documents: tuple[HomeSearchDocument, ...],
        top_k: int | None = None,
        reranker: HomeSearchReranker | None = None,
        scope: RunScope | None = None,
    ) -> HomeSearchResult:
        normalized_query = _normalize_text(query)
        if not normalized_query:
            raise AgentHomeContractError("Home top search query must be non-empty")
        if len(query) > self._settings.prefix_max_chars:
            raise AgentHomeContractError("Home top search query exceeds its size limit")
        limit = self._settings.default_top_k if top_k is None else top_k
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self._settings.max_top_k
        ):
            raise AgentHomeContractError(
                f"Home top search top_k must be between 1 and {self._settings.max_top_k}"
            )
        entries = tuple(self._entry(document) for document in documents)
        candidates = tuple(
            sorted(
                (
                    HomeSearchCandidate(
                        entry=entry,
                        score=_entry_score(normalized_query, entry),
                    )
                    for entry in entries
                ),
                key=lambda item: (-item.score, item.entry.link),
            )[: self._settings.candidate_limit]
        )
        selected = candidates[:limit]
        reranked = False
        if candidates and reranker is not None:
            if scope is None:
                raise AgentHomeContractError(
                    "Home top search reranking requires a runtime scope"
                )
            links = reranker.rerank(
                HomeSearchRequest(
                    query=query.strip(),
                    top_k=limit,
                    candidates=candidates,
                ),
                scope=scope,
            )
            validated = _validated_rerank(links, candidates=candidates, top_k=limit)
            if validated is not None:
                by_link = {candidate.entry.link: candidate for candidate in candidates}
                selected = tuple(by_link[link] for link in validated)
                reranked = True
        return HomeSearchResult(
            query=query.strip(),
            top_k=limit,
            candidate_count=len(candidates),
            reranked=reranked,
            items=tuple(_result_item(candidate) for candidate in selected),
        )

    def _entry(self, document: HomeSearchDocument) -> HomeSearchEntry:
        title, summary = _markdown_metadata(
            document.text_prefix,
            fallback_title=document.link.name,
            summary_max_chars=self._settings.summary_max_chars,
        )
        return HomeSearchEntry(
            link=str(document.link),
            space=document.link.space,
            title=title,
            summary=summary,
            digest=document.digest,
            searchable_prefix=_bounded_normalized(
                document.text_prefix,
                self._settings.prefix_max_chars,
            ),
            prefix_truncated=document.truncated,
        )


class HomeSearchModelRunner(Protocol):
    def run(self, call: TaskCall) -> TaskResult: ...


class LLMHomeSearchReranker:
    """Rerank bounded Home candidates through the dedicated JSON task profile."""

    def __init__(self, runner: HomeSearchModelRunner) -> None:
        self._runner = runner

    def rerank(
        self,
        request: HomeSearchRequest,
        *,
        scope: RunScope,
    ) -> tuple[str, ...] | None:
        result = self._runner.run(
            TaskCall(
                profile=TaskProfile.HOME_SEARCH,
                messages=MessageStack.of(
                    SystemMessage.from_text(
                        "Rank the supplied Agent Home candidates for the query. "
                        "Use only candidate links, do not invent links, and omit "
                        "candidates that are not relevant.",
                        label="home_search_role",
                    ),
                    UserMessage.from_json(
                        {
                            "query": request.query,
                            "top_k": request.top_k,
                            "candidates": [
                                {
                                    "link": item.entry.link,
                                    "space": item.entry.space,
                                    "title": item.entry.title,
                                    "summary": item.entry.summary,
                                    "searchable_prefix": item.entry.searchable_prefix,
                                    "prefix_truncated": item.entry.prefix_truncated,
                                }
                                for item in request.candidates
                            ],
                        },
                        label="home_search_candidates",
                    ),
                    UserMessage.from_text(
                        'Return exactly {"links":["home:space@name"]} with zero '
                        "or more unique candidate links in relevance order, up to "
                        "top_k. Return an empty list when no candidate is relevant.",
                        label="home_search_output",
                    ),
                ),
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                ),
                scope=scope,
            )
        )
        if result.status is TaskResultStatus.FAILURE:
            return None
        if not isinstance(result.answer, JsonAnswer):
            return None
        value = result.answer.value
        if set(value) != {"links"}:
            return None
        links = value.get("links")
        if not isinstance(links, list) or any(not isinstance(link, str) for link in links):
            return None
        return tuple(link for link in links if isinstance(link, str))


def _markdown_metadata(
    text: str,
    *,
    fallback_title: str,
    summary_max_chars: int,
) -> tuple[str, str]:
    lines = text.splitlines()
    title = next(
        (
            line[2:].strip()
            for line in lines
            if line.startswith("# ") and line[2:].strip()
        ),
        fallback_title,
    )
    title = _bounded_normalized(title, _TITLE_MAX_CHARS) or fallback_title
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(current)
    summary = ""
    for paragraph in paragraphs:
        body = [line for line in paragraph if not line.startswith("#")]
        if body:
            summary = _bounded_normalized(" ".join(body), summary_max_chars)
            if summary:
                break
    if not summary:
        summary = _bounded_normalized(text, summary_max_chars)
    return title, summary


def _entry_score(query: str, entry: HomeSearchEntry) -> int:
    link = _normalize_text(entry.link)
    name = _normalize_text(entry.link.split("@", 1)[-1])
    title = _normalize_text(entry.title)
    summary = _normalize_text(entry.summary)
    prefix = _normalize_text(entry.searchable_prefix)
    score = 0
    if query == link:
        score += 10_000
    if query in {name, title}:
        score += 5_000
    score += _field_score(query, link, exact_weight=1600, overlap_weight=320)
    score += _field_score(query, name, exact_weight=1400, overlap_weight=280)
    score += _field_score(query, title, exact_weight=1200, overlap_weight=240)
    score += _field_score(query, summary, exact_weight=700, overlap_weight=140)
    score += _field_score(query, prefix, exact_weight=400, overlap_weight=80)
    return score


def _field_score(
    query: str,
    value: str,
    *,
    exact_weight: int,
    overlap_weight: int,
) -> int:
    if not value:
        return 0
    score = exact_weight if query in value else 0
    query_units = _search_units(query)
    if not query_units:
        return score
    overlap = len(query_units.intersection(_search_units(value)))
    return score + (overlap * overlap_weight // len(query_units))


def _search_units(value: str) -> frozenset[str]:
    words = set(_WORD_PATTERN.findall(value))
    compact = "".join(character for character in value if character.isalnum())
    words.update(compact[index : index + 2] for index in range(len(compact) - 1))
    if len(compact) == 1:
        words.add(compact)
    return frozenset(words)


def _validated_rerank(
    links: tuple[str, ...] | None,
    *,
    candidates: tuple[HomeSearchCandidate, ...],
    top_k: int,
) -> tuple[str, ...] | None:
    if links is None or len(links) > top_k or len(links) != len(set(links)):
        return None
    allowed = {candidate.entry.link for candidate in candidates}
    if any(link not in allowed for link in links):
        return None
    return links


def _result_item(candidate: HomeSearchCandidate) -> HomeSearchItem:
    entry = candidate.entry
    return HomeSearchItem(
        link=entry.link,
        space=entry.space,
        title=entry.title,
        summary=entry.summary,
        digest=entry.digest,
        score=candidate.score,
    )


def _normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise AgentHomeContractError("Home top search query must be text")
    return " ".join(normalize("NFKC", value).casefold().split())


def _bounded_normalized(value: str, max_chars: int) -> str:
    normalized = " ".join(value.split())
    return normalized[:max_chars]
