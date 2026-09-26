"""Workspace's original line matcher, adapted to the shared query channel."""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from typing import Protocol

import regex

from tinysoul.kernel.retrieval.contracts import (
    EvidenceKind,
    QuerySource,
    SearchCandidate,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.disclosure import range_evidence

from ..config import WorkspaceSearchSettings


class _RegexMatch(Protocol):
    def span(self) -> tuple[int, int]: ...


class _RegexPattern(Protocol):
    def search(self, text: str, *, timeout: float) -> _RegexMatch | None: ...


class WorkspaceTextMatcher:
    """Return every matching resource and its exact original-text spans."""

    def __init__(self, settings: WorkspaceSearchSettings) -> None:
        self._settings = settings

    def match(
        self, source: QuerySource, query: str, candidates: tuple[SearchCandidate, ...]
    ) -> tuple[SearchCandidate, ...]:
        if (
            not query.strip()
            or "\n" in query
            or "\r" in query
            or len(query) > self._settings.max_query_chars
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Workspace query must be one nonempty line within its character limit",
            )
        try:
            pattern = (
                regex.compile(query, 0 if source.case_sensitive else regex.IGNORECASE)
                if source.regex
                else None
            )
        except regex.error as exc:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Workspace regular expression is invalid",
            ) from exc
        deadline = monotonic() + 0.2
        ranked = []
        for candidate in candidates:
            text = "".join(unit.text for unit in candidate.content_units)
            try:
                matches = _matching_lines(
                    text,
                    query,
                    case_sensitive=source.case_sensitive,
                    pattern=pattern,
                    deadline=deadline,
                )
            except TimeoutError as exc:
                raise SearchFailure(
                    SearchFailureKind.SCOPE_REQUIRED,
                    "Workspace regex exceeded its matching budget; simplify the pattern",
                ) from exc
            if not matches:
                continue
            evidence = []
            offset = 0
            for number, line in enumerate(text.splitlines(keepends=True), 1):
                if number in matches:
                    start, end = matches[number]
                    evidence.extend(
                        range_evidence(
                            candidate.content_units,
                            offset + start,
                            offset + max(end, start + 1),
                            kind=EvidenceKind.LEXICAL,
                        )
                    )
                offset += len(line)
            ranked.append(
                replace(
                    candidate,
                    evidence=tuple(evidence),
                    score_kind="lexical",
                    score=float(len(matches)),
                )
            )
        return tuple(sorted(ranked, key=lambda item: -(item.score or 0)))


def _matching_lines(
    text: str,
    query: str,
    *,
    case_sensitive: bool,
    pattern: _RegexPattern | None,
    deadline: float,
) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        line_text = line.rstrip("\r\n")
        if pattern is None:
            span = _literal_match_span(line_text, query, case_sensitive=case_sensitive)
        else:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            match = pattern.search(line_text, timeout=remaining)
            span = match.span() if match is not None else None
        if span is not None:
            result[line_number] = span
    return result


def _literal_match_span(
    text: str,
    query: str,
    *,
    case_sensitive: bool,
) -> tuple[int, int] | None:
    """Return the first literal match as original-text character offsets."""

    if case_sensitive:
        start = text.find(query)
        return None if start < 0 else (start, start + len(query))

    needle = query.casefold()
    if not needle:
        return None
    folded_start = text.casefold().find(needle)
    if folded_start < 0:
        return None
    folded_end = folded_start + len(needle)

    source_start: int | None = None
    folded_offset = 0
    for index, char in enumerate(text):
        next_offset = folded_offset + len(char.casefold())
        if source_start is None and next_offset > folded_start:
            source_start = index
        if source_start is not None and next_offset >= folded_end:
            return source_start, index + 1
        folded_offset = next_offset
    return None
