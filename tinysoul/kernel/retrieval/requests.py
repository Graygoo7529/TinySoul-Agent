"""Dynamic Action arguments become discriminated requests before source access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from .contracts import (
    BacklinksSource,
    DirectorySource,
    DocumentQuery,
    FilterStep,
    ModelStep,
    OperationKind,
    QuerySource,
    RefsSource,
    ResourceScope,
    ResourceScopeKind,
    ResultSource,
    RetrievalRequest,
    SearchContext,
    SearchFailure,
    SearchFailureKind,
    SourceKind,
    TextQuery,
)
from .policy import RetrievalPolicy


def parse_retrieval_request(
    parameters: JsonObject,
    policy: RetrievalPolicy,
) -> RetrievalRequest | str:
    """Normalize the finite source/step language before any owner access."""
    if "continuation" in parameters:
        if (
            set(parameters) != {"continuation"}
            or not isinstance(parameters["continuation"], str)
            or not parameters["continuation"]
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Continuation must be supplied alone"
            )
        return parameters["continuation"]
    try:
        unknown = set(parameters) - {"source", "exclude_refs", "steps", "page"}
        if unknown:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Unknown Search request field"
            )
        source_value = parameters.get("source")
        if not isinstance(source_value, Mapping):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Search requires a source object"
            )
        normalized = dict(source_value)
        if (
            normalized.get("kind") in {"query", "directory", "backlinks"}
            and "scope" not in normalized
            and policy.capability
            and policy.capability.resource_scope
        ):
            normalized["scope"] = {"kind": "workspace", "locator": ""}
        source = _parse_source(cast(Mapping[str, object], normalized))
        raw_steps = parameters.get("steps", [])
        if not isinstance(raw_steps, list):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "steps must be an array"
            )
        steps = tuple(_parse_step(value) for value in raw_steps)
        exclude = parameters.get("exclude_refs", [])
        if not isinstance(exclude, list) or any(
            not isinstance(item, str) for item in exclude
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "exclude_refs must be a string array"
            )
        page = parameters.get("page", {})
        if not isinstance(page, Mapping):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "page must be an object"
            )
        if set(page) - {"limit", "max_chars"}:
            raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Unknown page field")
        limit = page.get("limit", min(20, policy.page_max_items))
        max_chars = page.get("max_chars")
        if (
            type(limit) is not int
            or limit < 1
            or (max_chars is not None and (type(max_chars) is not int or max_chars < 1))
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Invalid page budget"
            )
        result = RetrievalRequest(
            source, steps, tuple(cast(str, item) for item in exclude), limit, max_chars
        )
        policy.validate_request(result)
        if result.page_limit > policy.page_max_items:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Page limit exceeds action policy"
            )
        return result
    except SearchFailure:
        raise
    except (ValueError, TypeError, JsonTypeError) as exc:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Invalid retrieval request"
        ) from exc


def _parse_source(value: Mapping[str, object]):
    kind = value.get("kind")
    try:
        source_kind = SourceKind(kind)
    except (ValueError, TypeError) as exc:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Unknown retrieval source"
        ) from exc
    if source_kind is SourceKind.QUERY:
        _reject_source_fields(
            value,
            {"kind", "scope", "query", "where", "literal", "regex", "case_sensitive"},
        )
        scope = _parse_scope(value.get("scope", "all"))
        query = value.get("query")
        where = to_json_object(value.get("where", {}))
        if not isinstance(scope, (str, ResourceScope)):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Query scope must be text"
            )
        if isinstance(query, str):
            parsed = TextQuery(query)
        elif isinstance(query, Mapping) and set(query) == {"document_ref"}:
            query_map = cast(Mapping[str, object], query)
            if not isinstance(query_map.get("document_ref"), str):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "Document query requires document_ref",
                )
            parsed = DocumentQuery(cast(str, query_map["document_ref"]))
        else:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Query source requires text or document_ref",
            )
        flags = ("literal", "regex", "case_sensitive")
        if any(type(value.get(name, False)) is not bool for name in flags):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Query matching flags must be boolean",
            )
        return QuerySource(
            scope,
            parsed,
            where,
            literal=cast(bool, value.get("literal", False)),
            regex=cast(bool, value.get("regex", False)),
            case_sensitive=cast(bool, value.get("case_sensitive", False)),
        )
    if source_kind is SourceKind.BACKLINKS:
        _reject_source_fields(value, {"kind", "scope", "anchor_ref", "where"})
        scope, anchor = _parse_scope(value.get("scope", "all")), value.get("anchor_ref")
        if not isinstance(scope, (str, ResourceScope)) or not isinstance(anchor, str):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Backlinks source requires scope and anchor_ref",
            )
        return BacklinksSource(scope, anchor, to_json_object(value.get("where", {})))
    if source_kind is SourceKind.DIRECTORY:
        _reject_source_fields(value, {"kind", "scope", "where"})
        scope = _parse_scope(value.get("scope", "all"))
        if not isinstance(scope, (str, ResourceScope)):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Directory scope must be text"
            )
        return DirectorySource(scope, to_json_object(value.get("where", {})))
    if source_kind is SourceKind.REFS:
        _reject_source_fields(value, {"kind", "refs"})
        refs = value.get("refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "refs must be a string array"
            )
        return RefsSource(tuple(cast(str, ref) for ref in refs))
    _reject_source_fields(value, {"kind", "result_ref"})
    result_ref = value.get("result_ref")
    if not isinstance(result_ref, str):
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "result source requires result_ref"
        )
    return ResultSource(result_ref)


def _reject_source_fields(value: Mapping[str, object], allowed: set[str]) -> None:
    if set(value) - allowed:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Unknown retrieval source field"
        )


def _parse_step(value: object):
    if not isinstance(value, Mapping):
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Search steps must be objects"
        )
    try:
        operation = OperationKind(value.get("op"))
    except (ValueError, TypeError) as exc:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Unknown search operation"
        ) from exc
    if operation is OperationKind.FILTER:
        if set(value) != {"op", "where"}:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Filter accepts only where"
            )
        where = value.get("where")
        if not isinstance(where, Mapping):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Filter where must be an object"
            )
        return FilterStep(to_json_object(cast(Mapping[str, object], where)))
    criterion = value.get("criterion")
    if not isinstance(criterion, str):
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Model operation requires criterion"
        )
    context = SearchContext(value.get("context", SearchContext.NONE.value))
    if set(value) - {"op", "criterion", "context"}:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Unknown model operation field"
        )
    return ModelStep(operation, criterion, context)


def _parse_scope(value: object) -> str | ResourceScope:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        fields = cast(Mapping[str, object], value)
        locator = fields.get("locator")
        if set(fields) == {"kind", "locator"} and isinstance(locator, str):
            return ResourceScope(ResourceScopeKind(fields["kind"]), locator)
    raise SearchFailure(SearchFailureKind.INVALID_REQUEST, "Invalid source scope")
