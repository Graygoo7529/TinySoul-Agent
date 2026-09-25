"""Deterministic document disclosure, with content-bound opaque continuation."""

from __future__ import annotations

from hashlib import sha256
import re
from markdown_it import MarkdownIt

from tinysoul.infra.continuation import OpaqueContinuationCodec, continue_json_sequence
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from .contracts import SearchFailure, SearchFailureKind, SearchEvidence


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
            for item in evidence_units(resource, selected, first_line=first)
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


def evidence_units(
    ref: str, text: str, *, max_chars: int = 2_000, first_line: int = 1
) -> tuple[SearchEvidence, ...]:
    """Bounded text units retain exact source lines, including long-line slices."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return (SearchEvidence(ref, ""),)
    result = []
    start, chunk = first_line, ""
    for number, line in enumerate(lines, first_line):
        if chunk and len(chunk) + len(line) > max_chars:
            result.append(SearchEvidence(f"{ref}#L{start}-L{number - 1}", chunk))
            start, chunk = number, ""
        chunk += line
        while len(chunk) > max_chars:
            result.append(
                SearchEvidence(f"{ref}#L{start}-L{number}", chunk[:max_chars])
            )
            start, chunk = number, chunk[max_chars:]
    if chunk:
        result.append(
            SearchEvidence(f"{ref}#L{start}-L{first_line + len(lines) - 1}", chunk)
        )
    return tuple(result)


def fragment_content(text: str, fragment: str) -> str:
    first, last = fragment_range(text, fragment)
    return "".join(text.splitlines(keepends=True)[first - 1 : last])


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
