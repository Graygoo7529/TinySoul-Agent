"""Model-facing Session Map refs and semantic node projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.action.call import ExecutionState
from tinysoul.kernel.context import ContextTurnFacts
from tinysoul.kernel.interaction import (
    InteractionNarrative,
    QuestionContent,
    input_projection,
)

from ..annotations.models import (
    AnnotationStatus,
    SemanticEdge,
    SemanticNode,
    SessionMap,
)
from ..completion import project_action_record, project_fact_refs
from ..errors import SessionContractError
from ..records.models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionTurnRecord,
)

_ACTION_COLLECTION = re.compile(
    r"^(session:turn/[0-9]{4}-[0-9]{2}-[0-9]{2}/[1-9][0-9]*)#actions$"
)
_ACTION_LEAF = re.compile(
    r"^(session:turn/[0-9]{4}-[0-9]{2}-[0-9]{2}/[1-9][0-9]*)#action/([0-9]+)$"
)


class SessionRelationKind(StrEnum):
    PRECEDES = "precedes"
    CONTAINS = "contains"
    REFERENCES = "references"
    REPLIES_TO = "replies_to"


def annotation_content(item: SemanticNode | SemanticEdge) -> JsonObject:
    return {"basis": "interpretation", **item.to_json()}


def annotation_relations(annotations: SessionMap, ref: str) -> tuple[SemanticEdge, ...]:
    return tuple(
        edge for edge in annotations.edges if ref in (edge.source, edge.target)
    )


def annotation_navigation(
    annotations: SessionMap, item: SemanticNode | SemanticEdge
) -> JsonObject:
    """One non-recursive forest entry; shared branches retain their own refs."""
    value = annotation_content(item)
    if isinstance(item, SemanticNode):
        value["relations"] = [
            annotation_content(edge)
            for edge in annotation_relations(annotations, item.ref)
            if edge.status is AnnotationStatus.ACTIVE
        ]
    return value


def project_relations(record: SessionTurnRecord) -> tuple[JsonObject, ...]:
    """Project only explicit edges; node content stays in its owning record."""
    values: list[JsonObject] = []

    def edge(source: str, target: str, relation: SessionRelationKind) -> None:
        values.append(
            {
                "kind": "relation",
                "source": source,
                "target": target,
                "relation": relation.value,
                "basis": "fact",
            }
        )

    def references(source: str, refs: tuple[str, ...]) -> None:
        for resource in dict.fromkeys(refs):
            target = resource_locator(record, resource)["ref"]
            assert isinstance(target, str)
            edge(source, target, SessionRelationKind.REFERENCES)

    questions = {
        action.result_id: action_leaf_ref(record.ref, index)
        for index, action in enumerate(record.actions)
        if action.action == "core.ask"
        and action.outcome is SessionActionOutcome.SUCCESS
    }
    previous = None
    for index, item in enumerate(record.inputs):
        ref = input_ref(record.ref, index)
        edge(record.ref, ref, SessionRelationKind.CONTAINS)
        if previous is not None:
            edge(previous, ref, SessionRelationKind.PRECEDES)
        previous = ref
        if item.reply_to:
            edge(ref, questions[item.reply_to], SessionRelationKind.REPLIES_TO)
    for index in range(len(record.notes)):
        edge(record.ref, f"{record.ref}#note/{index}", SessionRelationKind.CONTAINS)
    if record.output is not None:
        ref = f"{record.ref}#output"
        edge(record.ref, ref, SessionRelationKind.CONTAINS)
        references(ref, record.output.references)
    if record.working:
        edge(record.ref, f"{record.ref}#working", SessionRelationKind.CONTAINS)
    references(record.ref, record.background_refs)
    previous = None
    for index, action in enumerate(record.actions):
        ref = action_leaf_ref(record.ref, index)
        edge(record.ref, ref, SessionRelationKind.CONTAINS)
        if previous is not None:
            edge(previous, ref, SessionRelationKind.PRECEDES)
        previous = ref
        references(ref, action.references)
    return tuple(values)


def input_ref(turn_ref: str, occurrence: int) -> str:
    return f"{turn_ref}#input/{occurrence}"


def resource_refs(record: SessionTurnRecord) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *record.background_refs,
                *(record.output.references if record.output is not None else ()),
                *(ref for action in record.actions for ref in action.references),
            )
        )
    )


def resource_locator(record: SessionTurnRecord, ref: str) -> JsonObject:
    """Locate a historical reference occurrence without reading another owner."""
    value: JsonObject = {
        "kind": "resource",
        "ref": f"{record.ref}#resource/{resource_refs(record).index(ref)}",
        "target_ref": ref,
        "basis": "fact",
    }
    if ref.startswith("workspace:"):
        value["source_day"] = record.day
        value["locator"] = {"ref": ref, "day": record.day}
    elif ref in {"memory:current", "memory:latest", "memory:target"}:
        segment = record.segments.get("memory")
        bindings = (
            segment.get("resolved_references") if isinstance(segment, dict) else None
        )
        locator = bindings.get(ref) if isinstance(bindings, dict) else None
        if isinstance(locator, dict):
            value["locator"] = locator
        else:
            value["unresolved_origin"] = True
    return value


def project_occurrence(record: SessionTurnRecord, suffix: str) -> JsonObject:
    """Expand a detail directly from the sole stored Turn record."""
    if suffix == "output" and record.output is not None:
        return {
            "kind": "session_output",
            "ref": f"{record.ref}#output",
            **record.output.to_json(),
        }
    if suffix == "working":
        return {
            "kind": "session_working",
            "ref": f"{record.ref}#working",
            "working": record.working,
        }
    match = re.fullmatch(r"(input|resource|note)/([0-9]+)", suffix)
    if match is not None:
        index = int(match.group(2))
        if match.group(1) == "note" and index < len(record.notes):
            return {"ref": f"{record.ref}#{suffix}", **record.notes[index]}
        if match.group(1) == "input" and index < len(record.inputs):
            return {
                "kind": "session_input",
                "ref": input_ref(record.ref, index),
                **record.inputs[index].to_json(),
                "narrative": session_input_narrative(record, index),
                "title": session_input_title(record, index),
            }
        refs = resource_refs(record)
        if match.group(1) == "resource" and index < len(refs):
            return resource_locator(record, refs[index])
    raise SessionContractError("Unknown Session occurrence")


def session_input_title(record: SessionTurnRecord, index: int) -> str:
    return session_input_projection(record, index).title


def session_input_projection(
    record: SessionTurnRecord, index: int
) -> InteractionNarrative:
    item = record.inputs[index]
    if item.answer is not None:
        action = next(
            action for action in record.actions if action.result_id == item.reply_to
        )
        question = QuestionContent.from_json(action.result)
        return question.reply_projection(item.answer)
    return input_projection(item.text, initial=index == 0)


def session_input_narrative(record: SessionTurnRecord, index: int) -> str:
    return session_input_projection(record, index).text


@dataclass(frozen=True)
class SessionActionRef:
    turn_ref: str
    occurrence: int | None = None

    @property
    def is_collection(self) -> bool:
        return self.occurrence is None


def action_collection_ref(turn_ref: str) -> str:
    _require_turn_ref(turn_ref)
    return f"{turn_ref}#actions"


def action_leaf_ref(turn_ref: str, occurrence: int) -> str:
    _require_turn_ref(turn_ref)
    if (
        isinstance(occurrence, bool)
        or not isinstance(occurrence, int)
        or occurrence < 0
    ):
        raise SessionContractError("Session Action occurrence must be non-negative")
    return f"{turn_ref}#action/{occurrence}"


def parse_action_ref(ref: str) -> SessionActionRef | None:
    collection = _ACTION_COLLECTION.fullmatch(ref)
    if collection is not None:
        return SessionActionRef(turn_ref=collection.group(1))
    leaf = _ACTION_LEAF.fullmatch(ref)
    if leaf is not None:
        return SessionActionRef(
            turn_ref=leaf.group(1),
            occurrence=int(leaf.group(2)),
        )
    return None


def project_action(
    turn_ref: str,
    occurrence: int,
    action: SessionActionRecord,
) -> JsonObject:
    """Canonical Action detail shared by active evidence and completed history."""
    value: JsonObject = {
        "kind": "session_action",
        "ref": action_leaf_ref(turn_ref, occurrence),
        "turn_ref": turn_ref,
        "action": action.action,
        "request": action.request,
        "outcome": action.outcome.value,
    }
    if action.result:
        value["result"] = action.result
    if action.failure is not None:
        value["failure"] = action.failure.to_json()
    if action.references:
        value["references"] = list(action.references)
    return to_json_object(value)


@dataclass(frozen=True)
class SessionEvidence:
    """Disclose accepted inputs and settled Actions without completing a Turn."""

    facts: ContextTurnFacts

    def resolve(self, ref: str) -> tuple[str, JsonObject] | None:
        refs = project_fact_refs(
            self.facts.turn_id, self.facts.inputs, len(self.facts.actions)
        )
        target = refs.get(ref, ref)
        root = f"session:turn/{self.facts.turn_id}"
        for index, item in enumerate(self.facts.inputs):
            if target == f"{root}#input/{index}":
                projection = self.input_projection(index)
                return target, {
                    "kind": "session_input",
                    "ref": target,
                    "text": item.text,
                    "reply_to": item.reply_to,
                    "answer": item.answer.to_json() if item.answer else None,
                    "narrative": projection.text,
                    "title": projection.title,
                    "source_state": "active_turn",
                }
        for index, item in enumerate(self.facts.actions):
            if (
                target == action_leaf_ref(root, index)
                and item.state is ExecutionState.SETTLED
            ):
                return target, {
                    **project_action(root, index, project_action_record(item)),
                    "source_state": "active_turn",
                }
        return None

    def input_projection(self, index: int) -> InteractionNarrative:
        item = self.facts.inputs[index]
        question = next(
            (
                fact.result
                for fact in self.facts.actions
                if fact.result is not None and fact.result.result_id == item.reply_to
            ),
            None,
        )
        if question is not None and item.answer is not None:
            return QuestionContent.from_json(question.payload).reply_projection(
                item.answer
            )
        return input_projection(item.text, initial=index == 0)


def _require_turn_ref(ref: str) -> None:
    if (
        not isinstance(ref, str)
        or re.fullmatch(r"session:turn/[0-9]{4}-[0-9]{2}-[0-9]{2}/[1-9][0-9]*", ref)
        is None
    ):
        raise SessionContractError("Invalid Session Turn ref")
