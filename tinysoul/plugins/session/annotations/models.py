"""Typed annotations and small atomic changes, independent of persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
import re
from uuid import uuid4

from tinysoul.infra.json import JsonObject
from ..errors import SessionContractError


class AnnotationKind(StrEnum):
    THREAD = "thread"
    NOTE = "note"


class AnnotationStatus(StrEnum):
    ACTIVE = "active"
    RETRACTED = "retracted"


class SemanticRelation(StrEnum):
    COVERS = "covers"
    CONTINUES = "continues"
    BRANCHES_FROM = "branches_from"
    CLARIFIES = "clarifies"
    REVISES = "revises"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    RESOLVES = "resolves"
    STEERS = "steers"


class OrganizeFailureReason(StrEnum):
    INVALID_CHANGE = "invalid_change"
    UNKNOWN_REF = "unknown_ref"
    INVALID_SOURCE = "invalid_source"
    CONFLICT = "conflict"
    NO_HISTORY = "no_history"


class OrganizeRequestError(SessionContractError):
    def __init__(self, reason: OrganizeFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _reject(
    message: str, reason: OrganizeFailureReason = OrganizeFailureReason.INVALID_CHANGE
) -> None:
    raise OrganizeRequestError(reason, message)


def _text(value: object, name: str, limit: int, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
    ):
        _reject(f"{name} must be text within {limit} characters")
    assert isinstance(value, str)
    return value


def _refs(
    value: object, name: str, limit: int, *, empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        _reject(f"{name} must be a bounded list of references")
    assert isinstance(value, (list, tuple))
    result = tuple(_text(item, name, 240) for item in value)
    if (not empty and not result) or len(set(result)) != len(result):
        _reject(f"{name} must contain distinct references")
    return result


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _reject("Annotation fields do not match the declared object")
    assert isinstance(value, dict)
    return {str(key): item for key, item in value.items()}


def _identity(ref: str, kind: str) -> None:
    if (
        re.fullmatch(rf"(?:local:[a-zA-Z0-9_-]+|session:{kind}/[a-z0-9_-]+)", ref)
        is None
    ):
        _reject("Use an existing annotation ref or local:<key> for a new object")


@dataclass(frozen=True)
class SemanticNode:
    ref: str
    kind: AnnotationKind
    title: str
    body: str
    source_refs: tuple[str, ...]
    status: AnnotationStatus = AnnotationStatus.ACTIVE

    def __post_init__(self) -> None:
        _identity(self.ref, "node")
        _text(self.title, "title", 160)
        _text(self.body, "body", 4000)
        if not isinstance(self.kind, AnnotationKind) or not isinstance(
            self.status, AnnotationStatus
        ):
            _reject("Node requires a typed kind and status")
        object.__setattr__(
            self, "source_refs", _refs(self.source_refs, "source_refs", 32)
        )

    def to_json(self) -> JsonObject:
        return {
            "ref": self.ref,
            "kind": self.kind.value,
            "title": self.title,
            "body": self.body,
            "source_refs": list(self.source_refs),
            "status": self.status.value,
        }

    @classmethod
    def parse(cls, value: object, *, persisted: bool = False) -> SemanticNode:
        fields = {"ref", "kind", "title", "body", "source_refs"}
        data = _object(value, fields | ({"status"} if persisted else set()))
        try:
            return cls(
                _text(data["ref"], "ref", 240),
                AnnotationKind(data["kind"]),
                _text(data["title"], "title", 160),
                _text(data["body"], "body", 4000),
                _refs(data["source_refs"], "source_refs", 32),
                AnnotationStatus(data["status"])
                if persisted
                else AnnotationStatus.ACTIVE,
            )
        except (ValueError, TypeError) as exc:
            raise OrganizeRequestError(
                OrganizeFailureReason.INVALID_CHANGE,
                "Invalid annotation kind or status",
            ) from exc


@dataclass(frozen=True)
class SemanticEdge:
    ref: str
    source: str
    target: str
    relation: SemanticRelation
    body: str
    source_refs: tuple[str, ...]
    status: AnnotationStatus = AnnotationStatus.ACTIVE

    def __post_init__(self) -> None:
        _identity(self.ref, "edge")
        _text(self.source, "source", 240)
        _text(self.target, "target", 240)
        _text(self.body, "body", 4000)
        if not isinstance(self.relation, SemanticRelation) or not isinstance(
            self.status, AnnotationStatus
        ):
            _reject("Edge requires a typed relation and status")
        object.__setattr__(
            self, "source_refs", _refs(self.source_refs, "source_refs", 32)
        )

    def to_json(self) -> JsonObject:
        return {
            "ref": self.ref,
            "source": self.source,
            "target": self.target,
            "relation": self.relation.value,
            "body": self.body,
            "source_refs": list(self.source_refs),
            "status": self.status.value,
        }

    @classmethod
    def parse(cls, value: object, *, persisted: bool = False) -> SemanticEdge:
        data = _object(
            value,
            {"ref", "source", "target", "relation", "body", "source_refs"}
            | ({"status"} if persisted else set()),
        )
        try:
            return cls(
                _text(data["ref"], "ref", 240),
                _text(data["source"], "source", 240),
                _text(data["target"], "target", 240),
                SemanticRelation(data["relation"]),
                _text(data["body"], "body", 4000),
                _refs(data["source_refs"], "source_refs", 32),
                AnnotationStatus(data["status"])
                if persisted
                else AnnotationStatus.ACTIVE,
            )
        except (ValueError, TypeError) as exc:
            raise OrganizeRequestError(
                OrganizeFailureReason.INVALID_CHANGE, "Invalid relation or status"
            ) from exc


@dataclass(frozen=True)
class OrganizeChange:
    scope_refs: tuple[str, ...]
    nodes: tuple[SemanticNode, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()
    retract_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_refs", _refs(self.scope_refs, "scope_refs", 64))
        object.__setattr__(
            self, "retract_ids", _refs(self.retract_ids, "retract_ids", 96, empty=True)
        )
        if (
            len(self.nodes) > 32
            or len(self.edges) > 64
            or not (self.nodes or self.edges or self.retract_ids)
        ):
            _reject("Organize requires a bounded non-empty change")
        if any(not isinstance(item, SemanticNode) for item in self.nodes) or any(
            not isinstance(item, SemanticEdge) for item in self.edges
        ):
            _reject("Organize requires typed objects")
        refs = (
            *(item.ref for item in self.nodes),
            *(item.ref for item in self.edges),
            *self.retract_ids,
        )
        if len(set(refs)) != len(refs):
            _reject(
                "An object may only be changed once per call",
                OrganizeFailureReason.CONFLICT,
            )

    @classmethod
    def parse(cls, value: JsonObject) -> OrganizeChange:
        nodes, edges = value.get("upsert_nodes", []), value.get("upsert_edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            _reject("Upserts must be lists")
        assert isinstance(nodes, list) and isinstance(edges, list)
        return cls(
            _refs(value.get("scope_refs"), "scope_refs", 64),
            tuple(SemanticNode.parse(item) for item in nodes),
            tuple(SemanticEdge.parse(item) for item in edges),
            _refs(value.get("retract_ids", []), "retract_ids", 96, empty=True),
        )


@dataclass(frozen=True)
class OrganizeResult:
    changed_refs: tuple[str, ...] = ()
    created: tuple[tuple[str, str], ...] = ()
    failure: OrganizeFailureReason | None = None
    feedback: str = ""

    def __post_init__(self) -> None:
        if self.failure is not None and (
            self.changed_refs or self.created or not self.feedback
        ):
            raise SessionContractError(
                "Rejected changes cannot contain committed references"
            )


@dataclass(frozen=True)
class SessionMap:
    nodes: tuple[SemanticNode, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()

    def __post_init__(self) -> None:
        refs = tuple(item.ref for item in (*self.nodes, *self.edges))
        if len(set(refs)) != len(refs) or any(ref.startswith("local:") for ref in refs):
            _reject("Stored annotations require distinct stable identities")
        nodes = {item.ref: item for item in self.nodes}
        for edge in self.edges:
            for endpoint in (edge.source, edge.target):
                if endpoint.startswith("session:node/"):
                    node = nodes.get(endpoint)
                    if node is None or (
                        edge.status is AnnotationStatus.ACTIVE
                        and node.status is AnnotationStatus.RETRACTED
                    ):
                        _reject(
                            "Retracted nodes cannot retain active relations",
                            OrganizeFailureReason.CONFLICT,
                        )
                elif not endpoint.startswith("session:turn/"):
                    _reject("Relations must link semantic nodes or history facts")
            if edge.relation is SemanticRelation.COVERS:
                node = nodes.get(edge.source)
                if (
                    node is None
                    or node.kind is not AnnotationKind.THREAD
                    or not edge.target.startswith("session:turn/")
                ):
                    _reject("covers links a thread to a history fact")

    def get(self, ref: str) -> SemanticNode | SemanticEdge | None:
        return next(
            (item for item in (*self.nodes, *self.edges) if item.ref == ref), None
        )

    def to_json(self) -> JsonObject:
        return {
            "version": 1,
            "nodes": [item.to_json() for item in self.nodes],
            "edges": [item.to_json() for item in self.edges],
        }

    @classmethod
    def parse(cls, value: object) -> SessionMap:
        data = _object(value, {"version", "nodes", "edges"})
        nodes, edges = data["nodes"], data["edges"]
        if (
            type(data["version"]) is not int
            or data["version"] != 1
            or not isinstance(nodes, list)
            or not isinstance(edges, list)
        ):
            _reject("Invalid Session map document")
        assert isinstance(nodes, list) and isinstance(edges, list)
        return cls(
            tuple(SemanticNode.parse(item, persisted=True) for item in nodes),
            tuple(SemanticEdge.parse(item, persisted=True) for item in edges),
        )

    def apply(
        self,
        change: OrganizeChange,
        *,
        fact: Callable[[str, bool], str],
    ) -> tuple[SessionMap, OrganizeResult]:
        """Resolve every reference before producing a complete candidate."""
        for ref in change.scope_refs:
            if self.get(ref) is None:
                fact(ref, False)
        created = {
            item.ref: f"session:{kind}/{uuid4().hex}"
            for kind, items in (("node", change.nodes), ("edge", change.edges))
            for item in items
            if item.ref.startswith("local:")
        }
        nodes, edges = (
            {item.ref: item for item in self.nodes},
            {item.ref: item for item in self.edges},
        )

        def identity(ref: str, kind: str) -> str:
            if ref in created:
                return created[ref]
            if ref not in (nodes if kind == "node" else edges):
                _reject(
                    "Unknown annotation; use local:<key> to create it",
                    OrganizeFailureReason.UNKNOWN_REF,
                )
            return ref

        changed: list[str] = []
        for node in change.nodes:
            ref = identity(node.ref, "node")
            old = nodes.get(ref)
            if old is not None and old.kind is not node.kind:
                _reject(
                    "An existing node cannot change kind",
                    OrganizeFailureReason.CONFLICT,
                )
            nodes[ref] = replace(
                node,
                ref=ref,
                source_refs=tuple(fact(source, True) for source in node.source_refs),
            )
            changed.append(ref)
        for edge in change.edges:
            ref = identity(edge.ref, "edge")

            def endpoint(value: str) -> str:
                value = created.get(value, value)
                return value if value in nodes else fact(value, False)

            edges[ref] = replace(
                edge,
                ref=ref,
                source=endpoint(edge.source),
                target=endpoint(edge.target),
                source_refs=tuple(fact(source, True) for source in edge.source_refs),
            )
            changed.append(ref)
        for ref in change.retract_ids:
            if ref in nodes:
                nodes[ref] = replace(nodes[ref], status=AnnotationStatus.RETRACTED)
            elif ref in edges:
                edges[ref] = replace(edges[ref], status=AnnotationStatus.RETRACTED)
            else:
                _reject(
                    "Unknown annotation to retract", OrganizeFailureReason.UNKNOWN_REF
                )
            changed.append(ref)
        return SessionMap(tuple(nodes.values()), tuple(edges.values())), OrganizeResult(
            tuple(changed), tuple(created.items())
        )
