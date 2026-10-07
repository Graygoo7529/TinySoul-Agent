"""Deterministic document disclosure, with content-bound opaque continuation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from hashlib import sha256

from markdown_it import MarkdownIt

from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    ContinuationPosition,
    OpaqueContinuationCodec,
)
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.prompts.kernel import retrieval as prompt_text

from .contracts import (
    CandidatePreview,
    ContentCoverage,
    ContentSlice,
    ContentUnit,
    EvidenceKind,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
)


@dataclass(frozen=True)
class DisclosureHint:
    ref: str
    title: str
    clue: str = ""

    def __post_init__(self) -> None:
        if not self.ref or not self.title:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Disclosure needs a reference and title",
            )

    def to_json(self) -> JsonObject:
        return {"ref": self.ref, "title": self.title, "clue": self.clue}


@dataclass(frozen=True)
class DisclosureUnit:
    """Owner-projected narrative and its original machine facts, before paging."""

    ref: str
    title: str
    text: str
    data: JsonObject = field(default_factory=dict)
    first_line: int | None = None
    sections: tuple[tuple[int, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.ref or not self.title:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Disclosure needs a reference and title",
            )

    def select(self, start: int, end: int) -> DisclosureSlice:
        return DisclosureSlice(self, start, end)


@dataclass(frozen=True)
class DisclosureSlice:
    unit: DisclosureUnit
    start: int
    end: int

    def __post_init__(self) -> None:
        if not 0 <= self.start <= self.end <= len(self.unit.text):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Disclosure range is outside its content",
            )

    @property
    def title(self) -> str:
        section = next(
            (
                title
                for offset, title in reversed(self.unit.sections)
                if offset <= self.start
            ),
            "",
        )
        return self.unit.title + (f" · {section}" if section else "")

    @property
    def coverage(self) -> JsonObject:
        value: JsonObject = {
            "start": self.start,
            "end": self.end,
            "total": len(self.unit.text),
            "complete": self.start == 0 and self.end == len(self.unit.text),
        }
        if self.unit.first_line is not None:
            value["start_line"] = self.unit.first_line + self.unit.text[
                : self.start
            ].count("\n")
            value["end_line"] = (
                self.unit.first_line
                + self.unit.text[: self.end].count("\n")
                - int(self.end > self.start and self.unit.text[self.end - 1] == "\n")
            )
        return value

    def to_json(self) -> JsonObject:
        if self.coverage["complete"]:
            value = {**self.unit.data, "narrative": self.unit.text}
        else:
            value = {
                "kind": "content_slice",
                "text": self.unit.text[self.start : self.end],
            }
            if "kind" in self.unit.data:
                value["source_kind"] = self.unit.data["kind"]
            if "role" in self.unit.data:
                value["role"] = self.unit.data["role"]
        return {
            **value,
            "ref": self.unit.ref,
            "title": self.title,
            "coverage": self.coverage,
        }

    def recollection(self) -> JsonObject:
        return {
            "ref": self.unit.ref,
            "title": self.title,
            "clue": " ".join(self.unit.text[self.start : self.end].split())[:160],
            "coverage": self.coverage,
        }


@dataclass(frozen=True)
class InspectPage:
    """One selection supplies the public page, model text and bounded recollection."""

    ref: str
    title: str
    view: str
    items: tuple[DisclosureSlice, ...]
    next_continuation: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    query: str | None = None

    def to_json(self) -> JsonObject:
        return {
            **self.metadata,
            "ref": self.ref,
            "title": self.title,
            "view": self.view,
            "items": [item.to_json() for item in self.items],
            "next_continuation": self.next_continuation,
        }

    @property
    def model_text(self) -> str:
        return prompt_text.inspect_page(
            title=self.title,
            ref=self.ref,
            view=self.view,
            items=tuple(
                (
                    item.title,
                    item.unit.ref,
                    item.unit.text[item.start : item.end],
                    coverage_text(item.coverage),
                )
                for item in self.items
            ),
            continuation=self.next_continuation,
        )

    @property
    def canonical_payload(self) -> JsonObject:
        value: JsonObject = {
            "inspected": True,
            "ref": self.ref,
            "title": self.title,
            "view": self.view,
            "coverage": [item.recollection() for item in self.items],
            "has_more": self.next_continuation is not None,
        }
        if self.query is not None:
            value["query"] = self.query
        return value

    @property
    def recollection_text(self) -> str:
        return render_recollection(self.canonical_payload)


def render_recollection(value: JsonObject) -> str:
    """Render persisted reading facts; never imply a saved body or old token."""
    entries = value.get("coverage", [])
    coverage = []
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict):
                span = item.get("coverage", {})
                coverage.append(
                    prompt_text.inspect_read_item(
                        title=str(item.get("title", "")),
                        ref=str(item.get("ref", "")),
                        clue=str(item.get("clue", "")),
                        coverage=coverage_text(span) if isinstance(span, dict) else "",
                    )
                )
    return prompt_text.inspect_recollection(
        title=str(value.get("title", "")),
        ref=str(value.get("ref", "")),
        view=str(value.get("view", "content")),
        query=str(value.get("query", "")),
        coverage="\n".join(coverage),
        has_more=bool(value.get("has_more")),
    )


def coverage_text(value: JsonObject) -> str:
    return prompt_text.inspect_range(
        start=int(str(value["start"])),
        end=int(str(value["end"])),
        total=int(str(value["total"])),
        complete=value["complete"] is True,
        first_line=int(str(value["start_line"])) if "start_line" in value else None,
        last_line=int(str(value["end_line"])) if "end_line" in value else None,
    )


@dataclass(frozen=True)
class DisclosurePage:
    ref: str
    kind: str
    content: tuple[DisclosureUnit, ...] = ()
    children: tuple[DisclosureHint, ...] = ()
    related: tuple[JsonObject, ...] = ()
    sources: tuple[str, ...] = ()
    title: str = ""
    metadata: JsonObject = field(default_factory=dict)

    def render(
        self,
        *,
        codec: OpaqueContinuationCodec,
        max_chars: int,
        continuation: str | None = None,
        binding: JsonObject | None = None,
    ) -> InspectPage:
        units = (
            *self.content,
            *(
                DisclosureUnit(
                    h.ref,
                    h.title,
                    h.clue,
                    {"kind": "child", "text": h.clue, **h.to_json()},
                )
                for h in self.children
            ),
            *(
                DisclosureUnit(
                    self.ref,
                    str(r.get("relation", prompt_text.INSPECT_RELATION)),
                    prompt_text.inspect_relation(
                        source=str(r.get("source", "")),
                        relation=str(r.get("relation", "")),
                        target=str(r.get("target", "")),
                    ),
                    r,
                )
                for r in self.related
            ),
            *(
                DisclosureUnit(
                    ref,
                    prompt_text.INSPECT_SOURCE,
                    prompt_text.INSPECT_SOURCE,
                    {"kind": "source", "ref": ref},
                )
                for ref in self.sources
            ),
        )
        fingerprint = dumps_json(
            to_json_object(
                {
                    "items": [
                        {
                            "ref": u.ref,
                            "title": u.title,
                            "text": u.text,
                            "data": u.data,
                            "line": u.first_line,
                            "sections": [
                                [offset, title] for offset, title in u.sections
                            ],
                        }
                        for u in units
                    ],
                    "metadata": self.metadata,
                }
            )
        )
        bound = {**(binding or {}), "view": sha256(fingerprint.encode()).hexdigest()}
        position = codec.decode(continuation, ref=self.ref, binding=bound)
        if type(max_chars) is not int or max_chars <= 0:
            raise ContinuationError(
                ContinuationFailureReason.INVALID_LIMIT,
                prompt_text.INSPECT_POSITIVE_LIMIT,
            )
        if position.item_index > len(units) or (
            continuation and position.item_index == len(units)
        ):
            raise ContinuationError(
                ContinuationFailureReason.OUT_OF_RANGE,
                prompt_text.INSPECT_CONTINUATION_OUTSIDE,
            )
        title = self.title or (units[0].title if units else self.kind)

        def page(
            parts: tuple[DisclosureSlice, ...], index: int, offset: int = 0
        ) -> InspectPage:
            token = None
            if index < len(units):
                token = codec.encode(
                    ContinuationPosition(
                        index,
                        offset,
                        "sha256:" + sha256(units[index].text.encode()).hexdigest()
                        if offset
                        else "",
                    ),
                    ref=self.ref,
                    binding=bound,
                )
            return InspectPage(
                self.ref,
                title,
                self.kind,
                parts,
                token,
                {"kind": self.kind, **self.metadata},
                str(bound["query"]) if bound.get("query") is not None else None,
            )

        def fits(value: InspectPage) -> bool:
            return (
                len(dumps_json(value.to_json())) <= max_chars
                and len(value.model_text) <= max_chars
            )

        selected: tuple[DisclosureSlice, ...] = ()
        index, offset = position.item_index, position.char_offset
        while index < len(units):
            unit = units[index]
            if offset > len(unit.text):
                raise ContinuationError(
                    ContinuationFailureReason.OUT_OF_RANGE,
                    prompt_text.INSPECT_OFFSET_OUTSIDE,
                )
            whole = (*selected, unit.select(offset, len(unit.text)))
            candidate = page(whole, index + 1)
            if fits(candidate):
                selected, index, offset = whole, index + 1, 0
                continue
            if selected:
                return page(selected, index, offset)
            low, high, best = offset + 1, len(unit.text) - 1, None
            while low <= high:
                end = (low + high) // 2
                candidate = page((unit.select(offset, end),), index, end)
                if fits(candidate):
                    best, low = candidate, end + 1
                else:
                    high = end - 1
            if best is not None:
                return best
            raise ContinuationError(
                ContinuationFailureReason.BUDGET_TOO_SMALL,
                prompt_text.INSPECT_BUDGET_TOO_SMALL,
            )
        result = page(selected, index)
        if not fits(result):
            raise ContinuationError(
                ContinuationFailureReason.BUDGET_TOO_SMALL,
                prompt_text.INSPECT_METADATA_TOO_LARGE,
            )
        return result


def inspect_document(
    *,
    owner: str,
    ref: str,
    text: str,
    direct_refs: tuple[DisclosureHint, ...],
    view: str = "content",
    continuation: str | None = None,
    max_chars: int = 8_000,
    metadata: JsonObject | None = None,
) -> InspectPage:
    if view not in {"content", "direct_refs"}:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            prompt_text.INSPECT_VIEW_MUST_BE_CONTENT_OR_DIRECT_REFS,
        )
    if type(max_chars) is not int or max_chars < 512:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            prompt_text.INSPECT_PAGE_BUDGET_MUST_BE_AT_LEAST_CHARACTERS,
        )
    metadata = metadata or {}
    title = str(
        metadata.get("title") or metadata.get("display") or prompt_text.INSPECT_DOCUMENT
    )
    content = ()
    if view == "content":
        first, last = fragment_range(text, ref.partition("#")[2])
        selected = "".join(text.splitlines(keepends=True)[first - 1 : last])
        content = (DisclosureUnit(ref, title, selected, {"text": selected}, first),)
    return DisclosurePage(
        ref,
        view,
        content=content,
        children=direct_refs,
        title=title,
        metadata={"metadata": metadata},
    ).render(
        codec=OpaqueContinuationCodec(owner=owner, operation="inspect"),
        continuation=continuation,
        max_chars=max_chars,
        binding={"mode": view},
    )


def content_units(
    ref: str, text: str, *, max_chars: int = 2_000, first_line: int = 1
) -> tuple[ContentUnit, ...]:
    """Partition exact text without inserting separators, retaining line and column."""
    result: list[ContentUnit] = []
    line, column = first_line, 1
    for offset in range(0, max(1, len(text)), max_chars):
        chunk = text[offset : offset + max_chars]
        last = line + chunk.rstrip("\r\n").count("\n")
        location: JsonObject = {
            "line": line,
            "column": column,
            "end_line": last,
            "offset": offset,
        }
        identity = (
            f"{ref}:L{first_line}:{offset}:{sha256(chunk.encode()).hexdigest()[:16]}"
        )
        result.append(
            ContentUnit(identity, f"{ref}#L{line}-L{last}", chunk, location=location)
        )
        if "\n" in chunk:
            line += chunk.count("\n")
            column = len(chunk.rsplit("\n", 1)[-1]) + 1
        else:
            column += len(chunk)
    return tuple(result)


def range_evidence(
    units: tuple[ContentUnit, ...],
    start: int,
    end: int,
    *,
    kind: EvidenceKind,
    relation: str | None = None,
) -> tuple[SearchEvidence, ...]:
    """Map a source-text match to the units of that same source, without copying text."""
    result = []
    offset = 0
    for unit in units:
        stop = offset + len(unit.text)
        if start < stop and end > offset:
            result.append(
                SearchEvidence(
                    unit.id,
                    kind,
                    max(0, start - offset),
                    min(len(unit.text), end - offset),
                    relation,
                )
            )
        offset = stop
    return tuple(result)


def project_candidate(candidate: SearchCandidate, budget: int) -> CandidatePreview:
    """Share deterministic, evidence-aware excerpts between model input and pages."""
    units = {unit.id: unit for unit in candidate.content_units}
    decisions = candidate.evaluation.basis if candidate.evaluation else ()
    # Give the leading contribution of each channel space before its remaining hits.
    by_kind: dict[EvidenceKind, list[SearchEvidence]] = {}
    for hit in candidate.evidence:
        by_kind.setdefault(hit.kind, []).append(hit)
    leads = tuple(values[0] for values in by_kind.values())
    rest = tuple(hit for values in by_kind.values() for hit in values[1:])
    preferred = (*decisions, *leads)
    ordered = (*preferred, *rest)
    slots = min(max(1, len(preferred)), max(1, budget // 160))
    allowance = max(1, budget // slots)
    fragments: list[ContentSlice] = []
    remaining = budget
    for hit in ordered:
        if remaining <= 0:
            break
        unit = units[hit.unit_id]
        stop = hit.end if hit.end is not None else len(unit.text)
        size = min(remaining, allowance)
        start = max(0, hit.start - min(80, size // 4))
        end = min(len(unit.text), start + size)
        covered_index = next(
            (
                index
                for index, part in enumerate(fragments)
                if part.unit.id == unit.id
                and part.start <= hit.start
                and part.end >= min(stop, hit.start + size)
            ),
            None,
        )
        if covered_index is not None:
            part = fragments[covered_index]
            fragments[covered_index] = replace(
                part,
                evidence=part.evidence
                if any(
                    (entry.kind, entry.relation) == (hit.kind, hit.relation)
                    for entry in part.evidence
                )
                else (*part.evidence, hit),
            )
            continue
        fragments.append(ContentSlice(unit, start, end, (hit,)))
        remaining -= end - start
    for unit in candidate.content_units:
        if remaining <= 0:
            break
        # Fill uncovered ranges with original content, never duplicate an excerpt.
        spans = sorted(
            (part.start, part.end) for part in fragments if part.unit.id == unit.id
        )
        offset = 0
        for start, end in (*spans, (len(unit.text), len(unit.text))):
            stop = min(start, offset + remaining)
            if stop > offset or (not unit.text and not fragments):
                fragments.append(ContentSlice(unit, offset, stop))
                remaining -= stop - offset
            offset = max(offset, end)
    covered = 0
    for unit in candidate.content_units:
        end = 0
        for start, stop in sorted(
            (part.start, part.end) for part in fragments if part.unit.id == unit.id
        ):
            covered += max(0, stop - max(start, end))
            end = max(end, stop)
    coverage = candidate.content_coverage
    if coverage is ContentCoverage.FULL and covered < sum(
        len(unit.text) for unit in candidate.content_units
    ):
        coverage = ContentCoverage.EXCERPT
    return CandidatePreview(candidate, tuple(fragments), coverage)


def fragment_range(text: str, fragment: str) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    if not fragment:
        return 1, len(lines)
    match = re.fullmatch(r"L([1-9][0-9]*)(?:-L?([1-9][0-9]*))?", fragment)
    if match:
        first, last = int(match[1]), int(match[2] or match[1])
        if first <= last <= len(lines):
            return first, last
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            prompt_text.REQUESTED_LINE_FRAGMENT_IS_OUTSIDE_THE_DOCUMENT,
        )
    tokens = MarkdownIt("commonmark").parse(text)
    headings = [
        (int(token.tag[1:]), token.map[0] + 1, tokens[index + 1].content)
        for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.map
    ]
    occurrences: dict[str, int] = {}
    for index, (level, first, title) in enumerate(headings):
        slug = re.sub(r"[^\w\s-]", "", title).strip().lower().replace(" ", "-")
        repeat = occurrences.get(slug, 0)
        occurrences[slug] = repeat + 1
        identity = f"{slug}-{repeat}" if repeat else slug
        if identity == fragment:
            last = next(
                (
                    line - 1
                    for depth, line, _ in headings[index + 1 :]
                    if depth <= level
                ),
                len(lines),
            )
            return first, last
    raise SearchFailure(
        SearchFailureKind.INVALID_REQUEST,
        prompt_text.UNKNOWN_DOCUMENT_FRAGMENT,
    )
