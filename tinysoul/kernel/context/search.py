"""Search the raw sources installed in a Context, without rendering or unfolding it."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject, JsonValue, dumps_json
from tinysoul.infra.references import (
    ReferenceError,
    ReferenceResolver,
    ResourceTarget,
    markdown_references,
)
from tinysoul.kernel.retrieval.contracts import (
    AttributeField,
    AttributeFilters,
    AttributeKind,
    BacklinksSource,
    ContentUnit,
    DocumentQuery,
    EvidenceKind,
    QuerySource,
    RefsSource,
    RetrievalRequest,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.operations import SearchCorpus

CONTEXT_SEARCH_FILTERS = AttributeFilters(
    (
        AttributeField("source"),
        AttributeField("basis"),
        AttributeField("kind"),
        AttributeField("day", AttributeKind.DATE),
    )
)
from .disclosure import DisclosureReference, DisclosureSearchEntry


def disclosure_corpus(
    entries: tuple[DisclosureSearchEntry, ...],
    request: RetrievalRequest,
    references: ReferenceResolver,
) -> SearchCorpus:
    candidate_source = request.source
    if getattr(candidate_source, "scope", "all") not in {"all", "trace", "session"}:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            "Context scope must be trace, session or all",
        )
    if isinstance(candidate_source, QuerySource):
        if isinstance(candidate_source.query, DocumentQuery):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Context discovery requires a text query",
            )
        query = candidate_source.query.text
    else:
        query = ""
    predicates = CONTEXT_SEARCH_FILTERS.parse(getattr(candidate_source, "where", {}))

    def resolve(ref: str, source: DisclosureReference | None = None) -> ResourceTarget:
        if ref.startswith(("session:", "turn:")):
            resource, _, fragment = ref.partition("#")
            return ResourceTarget(resource, fragment)
        return references.resolve(ref, source_day=source.source_day if source else None)

    try:
        anchor = (
            resolve(candidate_source.anchor_ref)
            if isinstance(candidate_source, BacklinksSource)
            else None
        )
    except ReferenceError as exc:
        raise SearchFailure(SearchFailureKind.INVALID_REQUEST, str(exc)) from exc
    candidates = []
    for entry in entries:
        if entry.ref in request.exclude_refs:
            continue
        attributes: JsonObject = {
            "source": entry.source,
            "basis": entry.basis,
            "kind": entry.content.get("kind", entry.title),
            "day": entry.day.isoformat() if entry.day else None,
        }
        if getattr(candidate_source, "scope", "all") not in {
            "all",
            entry.source,
        } or not all(predicate.matches(attributes) for predicate in predicates):
            continue
        units = (
            ContentUnit(entry.ref, entry.ref, dumps_json(entry.content), "structured"),
        )
        evidence: tuple[SearchEvidence, ...] = ()
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
                            entry.ref, EvidenceKind.REFERENCE, relation=source.relation
                        )
                    )
            if not found:
                continue
            evidence = tuple(dict.fromkeys(found))
        candidates.append(
            SearchCandidate(entry.ref, entry.title, units, attributes, evidence)
        )
    if isinstance(candidate_source, RefsSource):
        order = {
            ref: index for index, ref in enumerate(dict.fromkeys(candidate_source.refs))
        }
        candidates.sort(key=lambda item: order.get(item.ref, len(order)))
    return SearchCorpus(tuple(candidates), query, len(entries))


def _markdown_targets(value: JsonValue) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(reference.target for reference in markdown_references(value))
    if isinstance(value, list):
        return tuple(ref for item in value for ref in _markdown_targets(item))
    if isinstance(value, dict):
        return tuple(ref for item in value.values() for ref in _markdown_targets(item))
    return ()
