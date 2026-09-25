"""Dynamic Action arguments become discriminated requests before source access."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object
from .contracts import (
    BacklinkSearch,
    DocumentQuery,
    QueryDiscovery,
    SearchContext,
    SearchFailure,
    SearchFailureKind,
    SearchMode,
    SearchOptions,
    SearchRequest,
    SearchSemantic,
    SeedRefinement,
    TextQuery,
)
from .policy import SearchPolicy


def parse_search_request(
    parameters: JsonObject,
    policies: tuple[SearchPolicy, ...],
    *,
    directory_seed: bool = False,
) -> SearchRequest | str:
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
        mode = SearchMode(
            parameters.get(
                "mode", "seed_refinement" if directory_seed else "query_discovery"
            )
        )
        policy = next((item for item in policies if item.mode is mode), None)
        if policy is None:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Search mode is not available for this source",
            )
        base = {"mode", "scope", "filters", "semantic", "context", "limit", "query"}
        allowed = base | (
            {"seed_refs"}
            if mode is SearchMode.SEED_REFINEMENT
            else {"anchor_ref"}
            if mode is SearchMode.BACKLINK_SEARCH
            else set()
        )
        if set(parameters) - allowed:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Search parameters do not match the selected mode",
            )
        scope = parameters.get("scope", "all")
        limit = parameters.get("limit", min(20, policy.result_limit))
        filters = to_json_object(parameters.get("filters", {}))
        if not isinstance(scope, str) or type(limit) is not int:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Search scope and limit have invalid types",
            )
        options = SearchOptions(
            scope,
            SearchSemantic(parameters.get("semantic", policy.default_semantic.value)),
            SearchContext(parameters.get("context", policy.default_context.value)),
            limit,
            filters,
        )
        policy.validate(options)
        query = parameters.get("query", "")
        if mode is SearchMode.QUERY_DISCOVERY:
            if isinstance(query, str):
                return QueryDiscovery(TextQuery(query), options)
            if (
                isinstance(query, dict)
                and set(query) == {"document_ref"}
                and isinstance(query["document_ref"], str)
            ):
                return QueryDiscovery(DocumentQuery(query["document_ref"]), options)
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Discovery requires text query or document_ref",
            )
        if not isinstance(query, str):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "This search mode requires a text query",
            )
        if mode is SearchMode.SEED_REFINEMENT:
            refs = parameters.get("seed_refs", [])
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) for ref in refs
            ):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "seed_refs must be a string array",
                )
            return SeedRefinement(
                query,
                options,
                tuple(ref for ref in refs if isinstance(ref, str)),
                directory_seed,
            )
        anchor = parameters.get("anchor_ref")
        if not isinstance(anchor, str):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Backlink search requires anchor_ref"
            )
        return BacklinkSearch(anchor, options, query)
    except (ValueError, TypeError, JsonTypeError) as exc:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST, "Invalid search parameter value"
        ) from exc


def eligible(
    attributes: JsonObject, filters: JsonObject, *, supported: frozenset[str]
) -> bool:
    """Only explicit owner-declared equality/membership eligibility, never relevance."""
    if set(filters) - supported:
        raise SearchFailure(
            SearchFailureKind.INVALID_REQUEST,
            "This source does not support the requested filter",
        )
    for expected in filters.values():
        if isinstance(expected, list):
            if not expected or any(
                not isinstance(value, (str, int, bool)) for value in expected
            ):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "Filter values must be nonempty scalar sets",
                )
        elif not isinstance(expected, (str, int, bool)):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Filter values must be scalars or arrays",
            )
    for key, expected in filters.items():
        actual = attributes.get(key)
        if isinstance(expected, list):
            if not expected or any(
                not isinstance(value, (str, int, bool)) for value in expected
            ):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    "Filter values must be nonempty scalar sets",
                )
            if isinstance(actual, list):
                if not all(value in actual for value in expected):
                    return False
            elif actual not in expected:
                return False
        elif not isinstance(expected, (str, int, bool)):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Filter values must be scalars or arrays",
            )
        elif isinstance(actual, list):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    return True
