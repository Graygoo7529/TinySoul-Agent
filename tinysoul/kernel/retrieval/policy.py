"""Configured finite search choices; model implementation belongs to its use binding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.json import JsonObject, JsonValue, to_json_object
from .contracts import (
    CandidateSource,
    SearchContext,
    SearchMode,
    SearchSemantic,
    SearchOptions,
    SearchFailure,
    SearchFailureKind,
)


@dataclass(frozen=True)
class SearchCapability:
    """Source-owned operations that configuration may expose to an Action."""

    action_id: str
    modes: tuple[SearchMode, ...]
    candidate_sources: tuple[CandidateSource, ...] = ()
    semantic: tuple[SearchSemantic, ...] = (
        SearchSemantic.NONE,
        SearchSemantic.RANK,
        SearchSemantic.SELECT,
    )

    def validate(self, policy: SearchPolicy) -> None:
        if (
            policy.mode not in self.modes
            or not set(policy.candidate_sources) <= set(self.candidate_sources)
            or not set(policy.allowed_semantic) <= set(self.semantic)
        ):
            raise ConfigError(
                "Search policy exceeds its source capability",
                key=f"action.models.search_policies.{self.action_id}",
            )


def validate_search_policies(
    capabilities: tuple[SearchCapability, ...], policies: tuple[SearchPolicy, ...]
) -> None:
    declared = {item.action_id: item for item in capabilities}
    if len(declared) != len(capabilities):
        raise ConfigError(
            "Search actions must have one source declaration",
            key="action.models.search_policies",
        )
    for policy in policies:
        if policy.action_id not in declared:
            raise ConfigError(
                "Search policy names an undeclared source action",
                key="action.models.search_policies",
            )
        declared[policy.action_id].validate(policy)


@dataclass(frozen=True)
class SearchPolicy:
    action_id: str
    mode: SearchMode
    candidate_sources: tuple[CandidateSource, ...] = ()
    default_semantic: SearchSemantic = SearchSemantic.NONE
    allowed_semantic: tuple[SearchSemantic, ...] = (SearchSemantic.NONE,)
    default_context: SearchContext = SearchContext.NONE
    allowed_context: tuple[SearchContext, ...] = (SearchContext.NONE,)
    candidate_limit: int = 100
    input_max_chars: int = 64_000
    result_limit: int = 50
    page_max_chars: int = 8_000
    evidence_max_chars: int = 1_200

    def __post_init__(self) -> None:
        if (
            not self.action_id
            or self.default_semantic not in self.allowed_semantic
            or self.default_context not in self.allowed_context
        ):
            raise ConfigError(
                "Search defaults must be allowed choices", key=self.action_id
            )
        if self.mode is SearchMode.QUERY_DISCOVERY and not self.candidate_sources:
            raise ConfigError(
                "Discovery requires configured candidate sources", key=self.action_id
            )
        if self.mode is not SearchMode.QUERY_DISCOVERY and self.candidate_sources:
            raise ConfigError(
                "Seed and backlink sources belong to their owner", key=self.action_id
            )
        if self.mode is SearchMode.SEED_REFINEMENT and self.allowed_semantic != (
            SearchSemantic.SELECT,
        ):
            raise ConfigError("Seed refinement requires selection", key=self.action_id)
        for name in (
            "candidate_limit",
            "input_max_chars",
            "result_limit",
            "page_max_chars",
            "evidence_max_chars",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ConfigError(
                    "Search budgets must be positive integers",
                    key=f"{self.action_id}.{name}",
                )
        if (
            self.page_max_chars < 2_048
            or self.evidence_max_chars + 1_024 > self.page_max_chars
        ):
            raise ConfigError(
                "Search page must fit bounded evidence and metadata", key=self.action_id
            )
        for choices in (
            self.candidate_sources,
            self.allowed_semantic,
            self.allowed_context,
        ):
            if len(set(choices)) != len(choices):
                raise ConfigError("Duplicate search policy choice", key=self.action_id)

    def validate(self, options: SearchOptions) -> None:
        if (
            options.semantic not in self.allowed_semantic
            or options.context not in self.allowed_context
            or options.limit > self.result_limit
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Search options exceed the configured mode capabilities",
            )

    def projection(self) -> JsonObject:
        return {
            "mode": self.mode.value,
            "semantic": {
                "default": self.default_semantic.value,
                "allowed": [v.value for v in self.allowed_semantic],
            },
            "context": {
                "default": self.default_context.value,
                "allowed": [v.value for v in self.allowed_context],
            },
            "max_limit": self.result_limit,
        }


def parse_search_policies(value: object) -> tuple[SearchPolicy, ...]:
    if not isinstance(value, list):
        raise ConfigError(
            "Search policies require a table array", key="action.models.search_policies"
        )
    result = []
    for raw in value:
        if not isinstance(raw, Mapping) or any(not isinstance(k, str) for k in raw):
            raise ConfigError(
                "Search policy requires named fields",
                key="action.models.search_policies",
            )
        row = dict(cast(Mapping[str, object], raw))
        reject_unknown_keys(
            row,
            set(SearchPolicy.__dataclass_fields__),
            key="action.models.search_policies",
        )
        action = row.get("action_id")
        if not isinstance(action, str):
            raise ConfigError(
                "Search policy requires action_id", key="action.models.search_policies"
            )
        try:
            mode = SearchMode(row.get("mode"))
            semantic = SearchSemantic(row.get("default_semantic", "none"))
            context = SearchContext(row.get("default_context", "none"))
            sources = _choices(CandidateSource, row.get("candidate_sources", []))
            semantics = _choices(
                SearchSemantic, row.get("allowed_semantic", [semantic.value])
            )
            contexts = _choices(
                SearchContext, row.get("allowed_context", [context.value])
            )
        except (ValueError, TypeError) as exc:
            raise ConfigError("Invalid search policy choices", key=action) from exc
        budgets: dict[str, int] = {}
        for name in (
            "candidate_limit",
            "input_max_chars",
            "result_limit",
            "page_max_chars",
            "evidence_max_chars",
        ):
            if name in row:
                amount = row[name]
                if type(amount) is not int:
                    raise ConfigError(
                        "Search budget must be an integer", key=f"{action}.{name}"
                    )
                budgets[name] = amount
        result.append(
            SearchPolicy(
                action, mode, sources, semantic, semantics, context, contexts, **budgets
            )
        )
    if len({(p.action_id, p.mode) for p in result}) != len(result):
        raise ConfigError(
            "Duplicate search policy", key="action.models.search_policies"
        )
    return tuple(result)


def _choices[E](enum: type[E], value: object) -> tuple[E, ...]:
    if not isinstance(value, list):
        raise ConfigError(
            "Policy choices must be arrays", key="action.models.search_policies"
        )
    return tuple(enum(item) for item in value)


def search_schema(
    base: JsonObject, policies: tuple[SearchPolicy, ...], *, action_id: str
) -> JsonObject:
    """The same policies constrain both Phase2 choices and operation normalization."""
    properties = base.get("properties", {})
    if not isinstance(properties, dict):
        raise ConfigError("Search tool schema requires properties", key=action_id)
    variants: list[JsonValue] = []
    if action_id == "workspace.search":
        discovery = to_json_object(base)
        discovery_props = dict(properties)
        discovery_props["mode"] = {"type": "string", "enum": ["query_discovery"]}
        discovery["properties"] = discovery_props
        variants.append(discovery)
    for policy in policies:
        if policy.action_id != action_id:
            continue
        fields: JsonObject = {
            "mode": {"type": "string", "enum": [policy.mode.value]},
            "scope": properties.get("scope", {"type": "string"}),
            "filters": properties.get("filters", {"type": "object"}),
            "semantic": {
                "type": "string",
                "enum": [v.value for v in policy.allowed_semantic],
                "default": policy.default_semantic.value,
            },
            "context": {
                "type": "string",
                "enum": [v.value for v in policy.allowed_context],
                "default": policy.default_context.value,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": policy.result_limit},
        }
        required: list[JsonValue] = ["mode"]
        if action_id == "workspace.search":
            fields["scope"] = {
                "type": "string",
                "description": "all, a workspace:path file, or workspace:directory/",
            }
        if policy.mode is SearchMode.QUERY_DISCOVERY:
            fields["query"] = properties.get(
                "query", {"type": "string", "minLength": 1}
            )
            required.append("query")
        elif policy.mode is SearchMode.SEED_REFINEMENT:
            fields["query"] = {"type": "string", "minLength": 1}
            required.append("query")
            if action_id != "expand.search":
                fields["seed_refs"] = {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
                required.append("seed_refs")
        else:
            fields["anchor_ref"] = {"type": "string", "minLength": 1}
            fields["query"] = {"type": "string"}
            required.append("anchor_ref")
        variants.append(
            {
                "type": "object",
                "properties": fields,
                "required": required,
                "additionalProperties": False,
            }
        )
    variants.append(
        {
            "type": "object",
            "properties": {"continuation": {"type": "string", "minLength": 1}},
            "required": ["continuation"],
            "additionalProperties": False,
        }
    )
    return {"type": "object", "oneOf": variants}
