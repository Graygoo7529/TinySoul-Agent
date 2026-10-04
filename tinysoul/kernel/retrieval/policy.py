"""Configured finite search choices; model implementation belongs to its use binding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TypeVar, cast

from tinysoul.prompts.kernel import retrieval as prompt_text
from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.json import JsonObject, JsonValue

from .contracts import (
    AttributeFilters,
    DocumentQuery,
    FilterStep,
    OperationKind,
    QueryChannel,
    QuerySource,
    ResourceScope,
    RetrievalRequest,
    SearchContext,
    SearchFailure,
    SearchFailureKind,
    SourceKind,
)

E = TypeVar("E", bound=StrEnum)


@dataclass(frozen=True)
class SearchCapability:
    """Code-owned source and operation semantics, narrowed by configuration."""

    action_id: str
    sources: tuple[SourceKind, ...]
    operations: tuple[OperationKind, ...] = ()
    scopes: tuple[str, ...] = ("all",)
    filters: AttributeFilters = AttributeFilters()
    resource_scope: bool = False
    document_query: bool = False
    lexical_syntax: bool = False
    server_scope: bool = False

    def scope_schema(self) -> JsonObject:
        if self.resource_scope:
            return {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["workspace", "directory", "file"],
                    },
                    "locator": {"type": "string"},
                },
                "required": ["kind", "locator"],
                "additionalProperties": False,
            }
        if self.server_scope:
            return {
                "type": "string",
                "description": prompt_text.ALL_OR_SERVER_REGISTERED_SERVER_ID,
            }
        return {"type": "string", "enum": list(self.scopes)}

    def where_schema(self) -> JsonObject:
        return self.filters.schema()


@dataclass(frozen=True)
class RetrievalOperationPolicy:
    operation: OperationKind
    allowed_context: tuple[SearchContext, ...] = (SearchContext.NONE,)
    input_max_chars: int = 64_000

    def __post_init__(self) -> None:
        if not self.allowed_context or len(set(self.allowed_context)) != len(
            self.allowed_context
        ):
            raise ConfigError(
                "Operation contexts must be unique", key=self.operation.value
            )
        if type(self.input_max_chars) is not int or self.input_max_chars < 1:
            raise ConfigError(
                "Operation input budget must be positive", key=self.operation.value
            )

    def projection(self) -> JsonObject:
        return {
            "allowed_context": [item.value for item in self.allowed_context],
            "input_max_chars": self.input_max_chars,
        }


@dataclass(frozen=True)
class RetrievalPolicy:
    action_id: str
    sources: tuple[SourceKind, ...]
    operations: tuple[OperationKind, ...]
    query_channels: tuple[QueryChannel, ...] = (QueryChannel.LEXICAL,)
    operation_policies: tuple[RetrievalOperationPolicy, ...] = ()
    max_steps: int = 8
    snapshot_max_chars: int = 4_000_000
    page_max_items: int = 50
    page_max_chars: int = 8_000
    capability: SearchCapability | None = None

    def __post_init__(self) -> None:
        if not self.action_id or not self.sources:
            raise ConfigError(
                "Retrieval policy requires action and sources", key=self.action_id
            )
        if len(set(self.sources)) != len(self.sources) or len(
            set(self.operations)
        ) != len(self.operations):
            raise ConfigError(
                "Retrieval policy choices must be unique", key=self.action_id
            )
        if (
            not self.query_channels
            or len(set(self.query_channels)) != len(self.query_channels)
            or not set(self.query_channels) <= set(QueryChannel)
        ):
            raise ConfigError("Unknown query channel", key=self.action_id)
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 32:
            raise ConfigError(
                "max_steps must be between one and 32", key=self.action_id
            )
        for name in ("snapshot_max_chars", "page_max_items", "page_max_chars"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ConfigError(
                    "Retrieval budgets must be positive", key=f"{self.action_id}.{name}"
                )
        configured = {item.operation for item in self.operation_policies}
        if not configured <= set(self.operations):
            raise ConfigError(
                "Operation policy is not exposed by this action", key=self.action_id
            )

    def operation(self, kind: OperationKind) -> RetrievalOperationPolicy:
        for item in self.operation_policies:
            if item.operation is kind:
                return item
        return RetrievalOperationPolicy(kind)

    def validate_request(self, request: RetrievalRequest) -> None:
        source_kind = request.source_kind
        if source_kind not in self.sources:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.REQUESTED_SOURCE_IS_NOT_AVAILABLE_FOR_THIS_ACTION,
            )
        if request.page_limit > self.page_max_items:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.PAGE_LIMIT_EXCEEDS_ACTION_POLICY,
            )
        if self.capability is not None:
            self._validate_source(request)
        steps = request.steps
        if len(steps) > self.max_steps:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.PIPELINE_STEP_LIMIT_EXCEEDED,
            )
        for step in steps:
            operation = step.op
            if operation not in self.operations:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.OPERATION_UNAVAILABLE,
                )
            if operation in {OperationKind.SELECT, OperationKind.RERANK}:
                context = getattr(step, "context", SearchContext.NONE)
                if context not in self.operation(operation).allowed_context:
                    raise SearchFailure(
                        SearchFailureKind.INVALID_REQUEST,
                        prompt_text.OPERATION_CONTEXT_UNAVAILABLE,
                    )

    def _validate_source(self, request: RetrievalRequest) -> None:
        capability = self.capability
        assert capability is not None
        scope = getattr(request.source, "scope", None)
        if scope is not None:
            valid = (
                isinstance(scope, ResourceScope)
                if capability.resource_scope
                else (
                    isinstance(scope, str)
                    and (
                        scope in capability.scopes
                        or (
                            capability.server_scope
                            and scope.startswith("server:")
                            and len(scope) > 7
                        )
                    )
                )
            )
            if not valid:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.SOURCE_SCOPE_IS_NOT_SUPPORTED_BY_THIS_OWNER,
                )
        if isinstance(request.source, QuerySource):
            if (
                isinstance(request.source.query, DocumentQuery)
                and not capability.document_query
            ):
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.THIS_OWNER_REQUIRES_A_TEXT_QUERY,
                )
            if (
                request.source.regex
                or request.source.literal
                or request.source.case_sensitive
            ) and not capability.lexical_syntax:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST,
                    prompt_text.THIS_OWNER_DOES_NOT_EXPOSE_LITERAL_REGEX_MATCHING,
                )
        conditions = [
            getattr(request.source, "where", {}),
            *(step.where for step in request.steps if isinstance(step, FilterStep)),
        ]
        for where in conditions:
            capability.filters.parse(where)

    def projection(self) -> JsonObject:
        return {
            "scope": self.capability.scope_schema() if self.capability else {},
            "where": self.capability.where_schema() if self.capability else {},
            "sources": [item.value for item in self.sources],
            "operations": [item.value for item in self.operations],
            "query": {"channels": [item.value for item in self.query_channels]},
            "steps": {
                item.operation.value: item.projection()
                for item in self.operation_policies
            },
            "max_steps": self.max_steps,
            "snapshot_max_chars": self.snapshot_max_chars,
            "page": {
                "max_items": self.page_max_items,
                "max_chars": self.page_max_chars,
            },
        }


def parse_retrieval_policies(value: object) -> tuple[RetrievalPolicy, ...]:
    if value in (None, {}):
        return ()
    if not isinstance(value, Mapping):
        raise ConfigError("action.retrieval must be a table", key="action.retrieval")
    result: list[RetrievalPolicy] = []

    for action_id, raw in value.items():
        if not isinstance(action_id, str) or "." not in action_id:
            raise ConfigError(
                "Retrieval requires atomic Action ID keys", key="action.retrieval"
            )
        table = _new_table(raw, key=f"action.retrieval.{action_id}")
        reject_unknown_keys(
            table,
            {
                "sources",
                "operations",
                "query",
                "select",
                "rerank",
                "filter",
                "max_steps",
                "snapshot_max_chars",
                "page",
            },
            key=f"action.retrieval.{action_id}",
        )
        sources = _new_choices(SourceKind, table.get("sources", []), key=action_id)
        operations = _new_choices(
            OperationKind, table.get("operations", []), key=action_id
        )
        query_table = _new_table(table.get("query", {}), key=f"{action_id}.query")
        reject_unknown_keys(query_table, {"channels"}, key=f"{action_id}.query")
        channels = _new_choices(
            QueryChannel,
            query_table.get("channels", [QueryChannel.LEXICAL.value]),
            key=f"{action_id}.query.channels",
        )
        op_policies: list[RetrievalOperationPolicy] = []
        for operation in (
            OperationKind.FILTER,
            OperationKind.SELECT,
            OperationKind.RERANK,
        ):
            if operation.value not in table:
                continue
            raw_op = _new_table(
                table[operation.value], key=f"{action_id}.{operation.value}"
            )
            reject_unknown_keys(
                raw_op,
                {"allowed_context", "input_max_chars"},
                key=f"{action_id}.{operation.value}",
            )
            contexts = _new_choices(
                SearchContext,
                raw_op.get("allowed_context", [SearchContext.NONE.value]),
                key=f"{action_id}.{operation.value}.allowed_context",
            )
            op_policies.append(
                RetrievalOperationPolicy(
                    operation,
                    contexts,
                    _new_int(
                        raw_op.get("input_max_chars", 64_000),
                        key=f"{action_id}.{operation.value}.input_max_chars",
                    ),
                )
            )
        page = _new_table(table.get("page", {}), key=f"{action_id}.page")
        reject_unknown_keys(page, {"max_items", "max_chars"}, key=f"{action_id}.page")
        result.append(
            RetrievalPolicy(
                action_id,
                sources,
                operations,
                channels,
                tuple(op_policies),
                _new_int(table.get("max_steps", 8), key=f"{action_id}.max_steps"),
                _new_int(
                    table.get("snapshot_max_chars", 4_000_000),
                    key=f"{action_id}.snapshot_max_chars",
                ),
                _new_int(page.get("max_items", 50), key=f"{action_id}.page.max_items"),
                _new_int(
                    page.get("max_chars", 8_000), key=f"{action_id}.page.max_chars"
                ),
            )
        )
    if len({item.action_id for item in result}) != len(result):
        raise ConfigError("Duplicate retrieval policy", key="action.retrieval")
    return tuple(result)


def validate_retrieval_policies(
    capabilities: tuple[SearchCapability, ...], policies: tuple[RetrievalPolicy, ...]
) -> None:
    declared = {item.action_id: item for item in capabilities}
    for policy in policies:
        capability = declared.get(policy.action_id)
        if capability is None:
            raise ConfigError(
                "Retrieval policy names an undeclared action",
                key=f"action.retrieval.{policy.action_id}",
            )
        supported_sources = set(capability.sources)
        supported_operations = set(capability.operations)
        if (
            not set(policy.sources) <= supported_sources
            or not set(policy.operations) <= supported_operations
        ):
            raise ConfigError(
                "Retrieval policy exceeds its code-owned capability",
                key=f"action.retrieval.{policy.action_id}",
            )


def retrieval_schema(base: JsonObject, policy: RetrievalPolicy) -> JsonObject:
    """Build one schema for the finite source/step language exposed to Phase2."""
    scope_schema = (
        policy.capability.scope_schema() if policy.capability else {"type": "string"}
    )
    where_schema = (
        policy.capability.where_schema() if policy.capability else {"type": "object"}
    )
    source_variants: list[JsonValue] = []
    for source in policy.sources:
        props: JsonObject = {"kind": {"enum": [source.value]}}
        required = ["kind"]
        if source is SourceKind.QUERY:
            props.update(
                {
                    "scope": scope_schema,
                    "query": {
                        "oneOf": [
                            {"type": "string", "minLength": 1},
                            {
                                "type": "object",
                                "properties": {
                                    "document_ref": {"type": "string", "minLength": 1}
                                },
                                "required": ["document_ref"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                    "where": where_schema,
                    "literal": {"type": "boolean"},
                    "regex": {"type": "boolean"},
                    "case_sensitive": {"type": "boolean"},
                }
            )
            if policy.capability is not None:
                if not policy.capability.document_query:
                    props["query"] = {"type": "string", "minLength": 1}
                if not policy.capability.lexical_syntax:
                    for key in ("literal", "regex", "case_sensitive"):
                        props.pop(key)
            required += ["query"]
        elif source is SourceKind.BACKLINKS:
            props.update(
                {
                    "scope": scope_schema,
                    "anchor_ref": {"type": "string", "minLength": 1},
                    "where": where_schema,
                }
            )
            required += ["anchor_ref"]
        elif source is SourceKind.DIRECTORY:
            props.update({"scope": scope_schema, "where": where_schema})
        elif source is SourceKind.REFS:
            props["refs"] = {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            }
            required.append("refs")
        else:
            props["result_ref"] = {"type": "string", "minLength": 1}
            required.append("result_ref")
        source_variants.append(
            cast(
                JsonValue,
                {
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": False,
                },
            )
        )
    steps: list[JsonValue] = []
    if OperationKind.FILTER in policy.operations:
        filter_schema = dict(where_schema)
        filter_schema["minProperties"] = 1
        steps.append(
            cast(
                JsonValue,
                {
                    "type": "object",
                    "properties": {
                        "op": {"enum": ["filter"]},
                        "where": filter_schema,
                    },
                    "required": ["op", "where"],
                    "additionalProperties": False,
                },
            )
        )
    for op in (OperationKind.SELECT, OperationKind.RERANK):
        if op in policy.operations:
            allowed = policy.operation(op).allowed_context
            steps.append(
                cast(
                    JsonValue,
                    {
                        "type": "object",
                        "properties": {
                            "op": {"enum": [op.value]},
                            "criterion": {"type": "string", "minLength": 1},
                            "context": {
                                "type": "string",
                                "enum": [item.value for item in allowed],
                            },
                        },
                        "required": ["op", "criterion"],
                        "additionalProperties": False,
                    },
                )
            )
    request: JsonObject = {
        "type": "object",
        "properties": {
            "source": {"oneOf": source_variants},
            "exclude_refs": {"type": "array", "items": {"type": "string"}},
            "steps": {
                "type": "array",
                "items": {"oneOf": steps} if steps else {"type": "object"},
                "maxItems": policy.max_steps if steps else 0,
            },
            "page": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": policy.page_max_items,
                    },
                    "max_chars": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
        "required": ["source"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "oneOf": [
            request,
            {
                "type": "object",
                "properties": {"continuation": {"type": "string", "minLength": 1}},
                "required": ["continuation"],
                "additionalProperties": False,
            },
        ],
    }


def _new_table(value: object, *, key: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError("Expected a table", key=key)
    return dict(cast(Mapping[str, object], value))


def _new_choices(enum: type[E], value: object, *, key: str) -> tuple[E, ...]:
    if not isinstance(value, list):
        raise ConfigError("Expected an array of choices", key=key)
    try:
        result = tuple(enum(item) for item in value)
    except (ValueError, TypeError) as exc:
        raise ConfigError("Unknown retrieval choice", key=key) from exc
    if len(set(result)) != len(result):
        raise ConfigError("Duplicate retrieval choice", key=key)
    return result


def _new_int(value: object, *, key: str) -> int:
    if type(value) is not int or value < 1:
        raise ConfigError("Expected a positive integer", key=key)
    return value


def resolve_retrieval_policies(
    capabilities: tuple[SearchCapability, ...],
    policies: tuple[RetrievalPolicy, ...],
    implementations: Mapping[str, str],
) -> tuple[RetrievalPolicy, ...]:
    validate_retrieval_policies(capabilities, policies)
    declared = {item.action_id: item for item in capabilities}
    resolved = []
    for policy in policies:
        operations = []
        for kind in policy.operations:
            operation = policy.operation(kind)
            if (
                implementations.get(f"{policy.action_id}.{kind.value}")
                == "embedding_similarity"
            ):
                operation = replace(operation, allowed_context=(SearchContext.NONE,))
            operations.append(operation)
        resolved.append(
            replace(
                policy,
                capability=declared[policy.action_id],
                operation_policies=tuple(operations),
            )
        )
    return tuple(resolved)
