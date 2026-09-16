"""Deterministic bounded text search for active Workspace resources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tinysoul.infra.filesystem import read_text_prefix
from tinysoul.infra.json import JsonObject, dumps_json

from .config import WorkspaceSearchSettings
from .errors import WorkspaceContractError, WorkspaceIOError
from .links import WORKSPACE_LINK_PREFIX, WorkspaceLink
from .manifest import WorkspaceResourceRecord


class WorkspaceSearchScopeKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    WORKSPACE = "workspace"


@dataclass(frozen=True)
class WorkspaceSearchScope:
    """One explicit deterministic text-search scope."""

    kind: WorkspaceSearchScopeKind
    locator: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WorkspaceSearchScopeKind):
            raise WorkspaceContractError("Workspace search scope kind is invalid")
        if self.kind is WorkspaceSearchScopeKind.WORKSPACE:
            if self.locator:
                raise WorkspaceContractError(
                    "Workspace-wide search scope cannot include a locator"
                )
            return
        if not isinstance(self.locator, str) or not self.locator:
            raise WorkspaceContractError(
                f"Workspace {self.kind.value} search scope requires a locator"
            )
        if self.kind is WorkspaceSearchScopeKind.FILE:
            WorkspaceLink.parse(self.locator)
            return
        if not self.locator.startswith(WORKSPACE_LINK_PREFIX) or not self.locator.endswith(
            "/"
        ):
            raise WorkspaceContractError(
                "Workspace directory scope prefix must use workspace:path/ form"
            )
        WorkspaceLink.parse(self.locator[:-1])

    def to_json(self) -> JsonObject:
        return {"kind": self.kind.value, "locator": self.locator}


@dataclass(frozen=True)
class WorkspaceSearchFragment:
    link: str
    digest: str
    start_line: int
    end_line: int
    match_lines: tuple[int, ...]
    text: str
    excerpt_truncated: bool = False
    start_column: int | None = None
    end_column: int | None = None

    def to_json(self, *, include_text: bool = True) -> JsonObject:
        range_payload: JsonObject = {
            "start_line": self.start_line,
            "end_line": self.end_line,
        }
        if self.start_column is not None:
            range_payload["start_column"] = self.start_column
        if self.end_column is not None:
            range_payload["end_column"] = self.end_column
        payload: JsonObject = {
            "link": self.link,
            "digest": self.digest,
            "range": range_payload,
            "match_lines": list(self.match_lines),
            "excerpt_truncated": self.excerpt_truncated,
        }
        if include_text:
            payload["text"] = self.text
        return payload


@dataclass(frozen=True)
class WorkspaceSearchLineHint:
    link: str
    digest: str
    line: int

    def to_json(self) -> JsonObject:
        return {"link": self.link, "digest": self.digest, "line": self.line}


@dataclass(frozen=True)
class WorkspaceSearchCoverage:
    complete: bool
    reason: str
    files_considered: int
    files_scanned: int
    characters_scanned: int
    skipped_count: int

    def to_json(self) -> JsonObject:
        return {
            "complete": self.complete,
            "reason": self.reason,
            "files_considered": self.files_considered,
            "files_scanned": self.files_scanned,
            "characters_scanned": self.characters_scanned,
            "skipped_count": self.skipped_count,
        }


@dataclass(frozen=True)
class WorkspaceTextSearchResult:
    query: str
    scope: WorkspaceSearchScope
    case_sensitive: bool
    top_k: int
    fragments: tuple[WorkspaceSearchFragment, ...]
    line_hints: tuple[WorkspaceSearchLineHint, ...]
    truncated: bool
    coverage: WorkspaceSearchCoverage
    match_line_count: int

    def to_json(self, *, include_text: bool = True) -> JsonObject:
        return {
            "query": self.query,
            "scope": self.scope.to_json(),
            "case_sensitive": self.case_sensitive,
            "top_k": self.top_k,
            "match_line_count": self.match_line_count,
            "fragments": [
                item.to_json(include_text=include_text) for item in self.fragments
            ],
            "line_hints": [item.to_json() for item in self.line_hints],
            "truncated": self.truncated,
            "coverage": self.coverage.to_json(),
        }


class WorkspaceTextSearchService:
    """Search validated text records under deterministic scan and result budgets."""

    def __init__(self, settings: WorkspaceSearchSettings) -> None:
        if not isinstance(settings, WorkspaceSearchSettings):
            raise WorkspaceContractError("Workspace search settings are invalid")
        self._settings = settings

    def search(
        self,
        *,
        query: str,
        scope: WorkspaceSearchScope,
        records: tuple[WorkspaceResourceRecord, ...],
        root: Path,
        case_sensitive: bool = False,
        top_k: int | None = None,
    ) -> WorkspaceTextSearchResult:
        normalized_query = _validate_query(query, self._settings.max_query_chars)
        if not isinstance(scope, WorkspaceSearchScope):
            raise WorkspaceContractError("Workspace search scope is invalid")
        if not isinstance(case_sensitive, bool):
            raise WorkspaceContractError(
                "Workspace search case_sensitive must be boolean"
            )
        limit = self._settings.default_top_k if top_k is None else top_k
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
            or limit > self._settings.max_top_k
        ):
            raise WorkspaceContractError(
                f"Workspace search top_k must be between 1 and {self._settings.max_top_k}"
            )

        candidates: list[WorkspaceSearchFragment] = []
        compact_hints: list[WorkspaceSearchLineHint] = []
        characters_scanned = 0
        files_scanned = 0
        skipped_count = 0
        match_line_count = 0
        coverage_complete = True
        coverage_reason = ""

        for record in records:
            remaining = self._settings.max_scan_chars - characters_scanned
            if remaining <= 0:
                coverage_complete = False
                coverage_reason = "scan_limit"
                break
            path = root / Path(record.relative_path)
            try:
                read = read_text_prefix(path, max_chars=remaining)
            except UnicodeDecodeError:
                skipped_count += 1
                coverage_complete = False
                coverage_reason = coverage_reason or "unreadable_text"
                continue
            except OSError as exc:
                raise WorkspaceIOError(
                    f"Failed to search Workspace resource {record.link}: {exc}"
                ) from exc
            files_scanned += 1
            characters_scanned += len(read.text)
            if read.truncated:
                coverage_complete = False
                coverage_reason = "scan_limit"
            match_lines = _matching_lines(
                read.text,
                normalized_query,
                case_sensitive=case_sensitive,
            )
            match_line_count += len(match_lines)
            stored_lines = match_lines[: max(0, self._settings.candidate_limit - len(compact_hints))]
            compact_hints.extend(
                WorkspaceSearchLineHint(record.link, record.digest, line)
                for line in stored_lines
            )
            if len(compact_hints) > self._settings.candidate_limit:
                del compact_hints[self._settings.candidate_limit :]
            candidates.extend(
                _candidate_fragments(
                    record,
                    read.text,
                    stored_lines,
                    query=normalized_query,
                    case_sensitive=case_sensitive,
                    context_lines=self._settings.context_lines,
                    max_excerpt_chars=self._settings.max_excerpt_chars,
                )
            )
            if read.truncated:
                break

        coverage = WorkspaceSearchCoverage(
            complete=coverage_complete,
            reason=coverage_reason,
            files_considered=len(records),
            files_scanned=files_scanned,
            characters_scanned=characters_scanned,
            skipped_count=skipped_count,
        )
        return self._bounded_result(
            query=normalized_query,
            scope=scope,
            case_sensitive=case_sensitive,
            top_k=limit,
            candidates=tuple(candidates),
            all_hints=tuple(compact_hints),
            coverage=coverage,
            match_line_count=match_line_count,
        )

    def _bounded_result(
        self,
        *,
        query: str,
        scope: WorkspaceSearchScope,
        case_sensitive: bool,
        top_k: int,
        candidates: tuple[WorkspaceSearchFragment, ...],
        all_hints: tuple[WorkspaceSearchLineHint, ...],
        coverage: WorkspaceSearchCoverage,
        match_line_count: int,
    ) -> WorkspaceTextSearchResult:
        fragments: list[WorkspaceSearchFragment] = []
        represented_lines: set[tuple[str, int]] = set()
        for candidate in candidates:
            if len(fragments) >= top_k:
                break
            proposed = (*fragments, candidate)
            trial = WorkspaceTextSearchResult(
                query=query,
                scope=scope,
                case_sensitive=case_sensitive,
                top_k=top_k,
                fragments=proposed,
                line_hints=(),
                truncated=True,
                coverage=coverage,
                match_line_count=match_line_count,
            )
            if len(dumps_json(trial.to_json())) > self._settings.max_result_chars:
                break
            fragments.append(candidate)
            represented_lines.update(
                (candidate.link, line)
                for line in candidate.match_lines
            )

        hints: list[WorkspaceSearchLineHint] = []
        for hint in all_hints:
            if (hint.link, hint.line) in represented_lines:
                continue
            trial = WorkspaceTextSearchResult(
                query=query,
                scope=scope,
                case_sensitive=case_sensitive,
                top_k=top_k,
                fragments=tuple(fragments),
                line_hints=(*hints, hint),
                truncated=True,
                coverage=coverage,
                match_line_count=match_line_count,
            )
            if len(dumps_json(trial.to_json())) > self._settings.max_result_chars:
                break
            hints.append(hint)

        represented = len(represented_lines) + len(hints)
        truncated = len(fragments) < len(candidates) or represented < match_line_count
        result = WorkspaceTextSearchResult(
            query=query,
            scope=scope,
            case_sensitive=case_sensitive,
            top_k=top_k,
            fragments=tuple(fragments),
            line_hints=tuple(hints),
            truncated=truncated,
            coverage=coverage,
            match_line_count=match_line_count,
        )
        if len(dumps_json(result.to_json())) > self._settings.max_result_chars:
            raise WorkspaceContractError(
                "Workspace search fixed result metadata exceeds its result budget"
            )
        return result


def _validate_query(query: str, max_chars: int) -> str:
    if not isinstance(query, str) or not query.strip():
        raise WorkspaceContractError("Workspace search query must be non-empty")
    if "\n" in query or "\r" in query:
        raise WorkspaceContractError("Workspace search query must be a single line")
    if len(query) > max_chars:
        raise WorkspaceContractError("Workspace search query exceeds its size limit")
    return query


def _matching_lines(text: str, query: str, *, case_sensitive: bool) -> tuple[int, ...]:
    result: list[int] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        line_text = line.rstrip("\r\n")
        if _literal_match_span(
            line_text,
            query,
            case_sensitive=case_sensitive,
        ) is not None:
            result.append(line_number)
    return tuple(result)


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


def _candidate_fragments(
    record: WorkspaceResourceRecord,
    text: str,
    match_lines: tuple[int, ...],
    *,
    query: str,
    case_sensitive: bool,
    context_lines: int,
    max_excerpt_chars: int,
) -> tuple[WorkspaceSearchFragment, ...]:
    if not match_lines:
        return ()
    lines = text.splitlines(keepends=True)
    windows: list[tuple[int, int, list[int]]] = []
    for line in match_lines:
        start = max(1, line - context_lines)
        end = min(len(lines), line + context_lines)
        if windows and start <= windows[-1][1] + 1:
            previous_start, previous_end, previous_matches = windows[-1]
            windows[-1] = (
                previous_start,
                max(previous_end, end),
                [*previous_matches, line],
            )
        else:
            windows.append((start, end, [line]))
    return tuple(
        _fragment_for_window(
            record,
            lines,
            start,
            end,
            tuple(matches),
            query=query,
            case_sensitive=case_sensitive,
            max_excerpt_chars=max_excerpt_chars,
        )
        for start, end, matches in windows
    )


def _fragment_for_window(
    record: WorkspaceResourceRecord,
    lines: list[str],
    start: int,
    end: int,
    match_lines: tuple[int, ...],
    *,
    query: str,
    case_sensitive: bool,
    max_excerpt_chars: int,
) -> WorkspaceSearchFragment:
    text = "".join(lines[start - 1 : end])
    if len(text) <= max_excerpt_chars:
        return WorkspaceSearchFragment(
            link=record.link,
            digest=record.digest,
            start_line=start,
            end_line=end,
            match_lines=match_lines,
            text=text,
        )
    match_line = match_lines[0]
    line_text = lines[match_line - 1].rstrip("\r\n")
    match_span = _literal_match_span(
        line_text,
        query,
        case_sensitive=case_sensitive,
    )
    if match_span is None:
        raise WorkspaceContractError(
            "Workspace search fragment no longer contains its recorded match"
        )
    match_start, match_end = match_span
    match_chars = match_end - match_start
    left_context = max(0, max_excerpt_chars - match_chars) // 3
    excerpt_start = max(0, match_start - left_context)
    excerpt_end = min(len(line_text), excerpt_start + max_excerpt_chars)
    if excerpt_end < match_end:
        excerpt_end = match_end
        excerpt_start = max(0, excerpt_end - max_excerpt_chars)
    if excerpt_end - excerpt_start < max_excerpt_chars:
        excerpt_start = max(0, excerpt_end - max_excerpt_chars)
    excerpt = line_text[excerpt_start:excerpt_end]
    return WorkspaceSearchFragment(
        link=record.link,
        digest=record.digest,
        start_line=match_line,
        end_line=match_line,
        match_lines=(match_line,),
        text=excerpt,
        excerpt_truncated=True,
        start_column=excerpt_start + 1,
        end_column=excerpt_end,
    )
