"""Deterministic document disclosure, with content-bound opaque continuation."""

from __future__ import annotations

import re
from dataclasses import replace
from hashlib import sha256

from markdown_it import MarkdownIt

from tinysoul.infra.continuation import OpaqueContinuationCodec, continue_json_sequence
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object

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


def inspect_document(
    *,
    owner: str,
    ref: str,
    text: str,
    direct_refs: tuple[str, ...],
    view: str = "content",
    continuation: str | None = None,
    max_chars: int = 8_000,
    metadata: JsonObject | None = None,
) -> JsonObject:
    if view not in {"content", "direct_refs"}:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            "Inspect view must be content or direct_refs",
        )
    if type(max_chars) is not int or max_chars < 512:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            "Inspect page budget must be at least 512 characters",
        )
    resource, _, fragment = ref.partition("#")
    if view == "content":
        first, last = fragment_range(text, fragment)
        selected = "".join(text.splitlines(keepends=True)[first - 1 : last])
        values: tuple[JsonValue, ...] = tuple(
            {"ref": item.ref, "text": item.text}
            for item in content_units(resource, selected, first_line=first)
        )
    else:
        values = tuple(to_json_object({"ref": target}) for target in direct_refs)
    binding = {
        "digest": sha256(
            (text if view == "content" else "\n".join(direct_refs)).encode()
        ).hexdigest(),
        "view": view,
        "max_chars": max_chars,
    }
    return continue_json_sequence(
        values,
        base={"ref": ref, "view": view, "metadata": metadata or {}},
        item_field="items",
        continuation=continuation,
        codec=OpaqueContinuationCodec(owner=owner, operation="inspect"),
        ref=ref,
        max_chars=max_chars,
        binding=binding,
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
            "Requested line fragment is outside the document",
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
        "Document fragment does not identify a known heading or line range",
    )
