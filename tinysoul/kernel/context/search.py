"""Search the raw sources installed in a Context, without rendering or unfolding it."""

from __future__ import annotations

from tinysoul.infra.json import JsonValue, JsonObject, dumps_json
from tinysoul.infra.references import (
    ReferenceResolver,
    ReferenceError,
    ResourceTarget,
    markdown_references,
)
from tinysoul.kernel.retrieval.contracts import (
    SearchRequest,
    QueryDiscovery,
    DocumentQuery,
    BacklinkSearch,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.operations import SearchCorpus
from tinysoul.kernel.retrieval.requests import eligible
from .disclosure import DisclosureSearchEntry, DisclosureReference


def disclosure_corpus(
    entries: tuple[DisclosureSearchEntry, ...],
    request: SearchRequest,
    references: ReferenceResolver,
) -> SearchCorpus:
    if request.options.scope not in {"all", "trace", "session"}:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            "Context scope must be trace, session or all",
        )
    if isinstance(request, QueryDiscovery):
        if isinstance(request.query, DocumentQuery):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Context discovery requires a text query",
            )
        query = request.query.text
    else:
        query = request.query
    supported = frozenset({"source", "basis", "kind", "day"})
    eligible({}, request.options.filters, supported=supported)

    def resolve(ref: str, source: DisclosureReference | None = None) -> ResourceTarget:
        if ref.startswith(("session:", "turn:")):
            resource, _, fragment = ref.partition("#")
            return ResourceTarget(resource, fragment)
        return references.resolve(ref, source_day=source.source_day if source else None)

    try:
        anchor = (
            resolve(request.anchor_ref) if isinstance(request, BacklinkSearch) else None
        )
    except ReferenceError as exc:
        raise SearchFailure(SearchFailureKind.INVALID_REQUEST, str(exc)) from exc
    candidates = []
    for entry in entries:
        attributes: JsonObject = {
            "source": entry.source,
            "basis": entry.basis,
            "kind": entry.content.get("kind", entry.title),
            "day": entry.day.isoformat() if entry.day else None,
        }
        if request.options.scope not in {"all", entry.source} or not eligible(
            attributes, request.options.filters, supported=supported
        ):
            continue
        evidence = (SearchEvidence(entry.ref, dumps_json(entry.content)),)
        if anchor is not None:
            found = []
            links = (
                *entry.references,
                *(
                    DisclosureReference(link, "markdown_link", entry.day)
                    for link in _markdown_targets(entry.content)
                ),
            )
            for source in links:
                try:
                    target = resolve(source.target, source)
                except ReferenceError:
                    continue
                if target.matches(anchor):
                    found.append(
                        SearchEvidence(
                            entry.ref,
                            f"{source.relation}: {source.target}\n"
                            + dumps_json(entry.content),
                            source.relation,
                        )
                    )
            if not found:
                continue
            evidence = tuple(dict.fromkeys(found))
        candidates.append(SearchCandidate(entry.ref, entry.title, evidence, attributes))
    return SearchCorpus(tuple(candidates), query, len(entries))


def _markdown_targets(value: JsonValue) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(reference.target for reference in markdown_references(value))
    if isinstance(value, list):
        return tuple(ref for item in value for ref in _markdown_targets(item))
    if isinstance(value, dict):
        return tuple(ref for item in value.values() for ref in _markdown_targets(item))
    return ()
