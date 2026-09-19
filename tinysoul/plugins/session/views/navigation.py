"""Model-facing Session Map refs and semantic node projections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
import re

from tinysoul.kernel.action import ActionLocalFailure
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object

from ..errors import SessionContractError
from ..records.models import (
    SessionActionOutcome,
    SessionActionRecord,
    SessionTurnRecord,
)

_ACTION_COLLECTION = re.compile(r"^(session:turn/[a-z0-9_-]+)#actions$")
_ACTION_LEAF = re.compile(r"^(session:turn/[a-z0-9_-]+)#action/([0-9]+)$")
_FAILED_RESULT_PREVIEW_CHARS = 1200
_FAILURE_FEEDBACK_PREVIEW_CHARS = 800
_TURN_TEXT_PREVIEW_CHARS = 600


class SessionRelationKind(StrEnum):
    PRECEDES = "precedes"
    CONTAINS = "contains"
    REFERENCES = "references"
    REPLIES_TO = "replies_to"


def project_map(records: tuple[SessionTurnRecord, ...]) -> tuple[JsonObject, ...]:
    """Derive nodes and explicit factual edges; never infer semantic relationships."""

    values: list[JsonObject] = []
    resources: dict[tuple[str, str], str] = {}
    previous: str | None = None

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

    def references(
        source: str, refs: tuple[str, ...], record: SessionTurnRecord
    ) -> None:
        for ref in dict.fromkeys(refs):
            key = (record.day if ref.startswith("workspace:") else "", ref)
            if key not in resources:
                locator = resource_locator(record, ref)
                resources[key] = str(locator["ref"])
                values.append(locator)
            edge(source, resources[key], SessionRelationKind.REFERENCES)

    for record in records:
        values.append(project_navigation_header(record))
        if previous is not None:
            edge(previous, record.ref, SessionRelationKind.PRECEDES)
        previous = record.ref
        questions = {
            action.result_id: action_leaf_ref(record.ref, index)
            for index, action in enumerate(record.actions)
            if action.action == "core.ask"
            and action.outcome is SessionActionOutcome.SUCCESS
        }
        previous_input: str | None = None
        for index, item in enumerate(record.inputs):
            ref = input_ref(record.ref, index)
            values.append(
                {
                    "kind": "input",
                    "ref": ref,
                    "input_kind": (
                        "reply"
                        if item.reply_to
                        else "initial" if index == 0 else "append"
                    ),
                }
            )
            edge(record.ref, ref, SessionRelationKind.CONTAINS)
            if previous_input is not None:
                edge(previous_input, ref, SessionRelationKind.PRECEDES)
            previous_input = ref
            if item.reply_to:
                edge(ref, questions[item.reply_to], SessionRelationKind.REPLIES_TO)
        if record.output is not None:
            ref = f"{record.ref}#output"
            values.append({"kind": "output", "ref": ref})
            edge(record.ref, ref, SessionRelationKind.CONTAINS)
            references(ref, record.output.references, record)
        if record.working:
            ref = f"{record.ref}#working"
            values.append({"kind": "working", "ref": ref})
            edge(record.ref, ref, SessionRelationKind.CONTAINS)
        references(record.ref, record.background_links, record)
        previous_action: str | None = None
        for index, action in enumerate(record.actions):
            ref = action_leaf_ref(record.ref, index)
            values.append(
                {
                    "kind": "action",
                    "ref": ref,
                    "action": action.action,
                    "outcome": action.outcome.value,
                }
            )
            edge(record.ref, ref, SessionRelationKind.CONTAINS)
            if previous_action is not None:
                edge(previous_action, ref, SessionRelationKind.PRECEDES)
            previous_action = ref
            references(ref, action.references, record)
    return tuple(values)


def input_ref(turn_ref: str, occurrence: int) -> str:
    return f"{turn_ref}#input/{occurrence}"


def resource_links(record: SessionTurnRecord) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *record.background_links,
                *(record.output.references if record.output is not None else ()),
                *(ref for action in record.actions for ref in action.references),
            )
        )
    )


def resource_locator(record: SessionTurnRecord, link: str) -> JsonObject:
    """Locate a historical reference occurrence without reading another owner."""
    value: JsonObject = {
        "kind": "resource",
        "ref": f"{record.ref}#resource/{resource_links(record).index(link)}",
        "link": link,
        "basis": "fact",
    }
    if link.startswith("workspace:"):
        value["source_day"] = record.day
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
    match = re.fullmatch(r"(input|resource)/([0-9]+)", suffix)
    if match is not None:
        index = int(match.group(2))
        if match.group(1) == "input" and index < len(record.inputs):
            return {
                "kind": "session_input",
                "ref": input_ref(record.ref, index),
                **record.inputs[index].to_json(),
            }
        links = resource_links(record)
        if match.group(1) == "resource" and index < len(links):
            return resource_locator(record, links[index])
    raise SessionContractError("Unknown Session occurrence")


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


def project_navigation_header(record: SessionTurnRecord) -> JsonObject:
    value: JsonObject = {
        "kind": "turn",
        "ref": record.ref,
        "day": record.day,
        "status": record.status.value,
        "input_count": len(record.inputs),
        "ask": [_text_preview(item.text) for item in record.inputs[-3:]],
        "excerpted": len(record.inputs) > 3
        or any(len(item.text) > _TURN_TEXT_PREVIEW_CHARS for item in record.inputs),
    }
    if record.output is not None:
        value["answer"] = _text_preview(record.output.text)
        value["excerpted"] = (
            bool(value["excerpted"])
            or len(record.output.text) > _TURN_TEXT_PREVIEW_CHARS
        )
    outcomes = action_outcomes(record)
    if outcomes:
        value["action_outcomes"] = list(outcomes)
    return to_json_object(value)


def action_outcomes(record: SessionTurnRecord) -> tuple[JsonObject, ...]:
    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {outcome.value: 0 for outcome in SessionActionOutcome}
    )
    for action in record.actions:
        counters[action.action][action.outcome.value] += 1
    values: list[JsonObject] = []
    for action_name in sorted(counters):
        counts = {name: count for name, count in counters[action_name].items() if count}
        values.append(to_json_object({"action": action_name, "counts": counts}))
    return tuple(to_json_object(value) for value in values)


def project_turn(record: SessionTurnRecord) -> JsonObject:
    value: JsonObject = {
        "kind": "session_turn",
        "ref": record.ref,
        "status": record.status.value,
        "day": record.day,
        "ask": [item.text for item in record.inputs],
        "inputs": [
            {
                "ref": input_ref(record.ref, index),
                "input_id": item.input_id,
                "reply_to": item.reply_to,
            }
            for index, item in enumerate(record.inputs)
        ],
    }
    if record.output is not None:
        value["answer"] = record.output.text
        value["output_ref"] = f"{record.ref}#output"
        if record.output.references:
            value["references"] = list(record.output.references)
    if record.exhausted:
        value["exhausted"] = True
    if record.working:
        value["working_ref"] = f"{record.ref}#working"
    if record.failure is not None:
        value["failure"] = record.failure.to_json()
    if record.finish_failures:
        value["finish_failures"] = [item.to_json() for item in record.finish_failures]
    outcomes = action_outcomes(record)
    if outcomes:
        value["actions"] = {
            "ref": action_collection_ref(record.ref),
            "count": len(record.actions),
            "outcomes": list(outcomes),
        }
    return to_json_object(value)


def project_action_header(
    turn_ref: str,
    occurrence: int,
    action: SessionActionRecord,
) -> JsonObject:
    value: JsonObject = {
        "ref": action_leaf_ref(turn_ref, occurrence),
        "action": action.action,
        "outcome": action.outcome.value,
        "result_id": action.result_id,
    }
    if action.failure is not None:
        value["failure"] = _failure_preview(action.failure)
    if action.outcome.value != "success" and action.result:
        if len(dumps_json(action.result)) <= _FAILED_RESULT_PREVIEW_CHARS:
            value["result"] = action.result
        else:
            value["result_available"] = True
    return to_json_object(value)


def project_action(
    turn_ref: str,
    occurrence: int,
    action: SessionActionRecord,
) -> JsonObject:
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


def _failure_preview(failure: ActionLocalFailure) -> JsonObject:
    value: JsonObject = {
        "reason": failure.reason,
        "disposition": failure.disposition.value,
        "feedback": (
            failure.feedback
            if len(failure.feedback) <= _FAILURE_FEEDBACK_PREVIEW_CHARS
            else failure.feedback[: _FAILURE_FEEDBACK_PREVIEW_CHARS - 3] + "..."
        ),
    }
    if failure.constraint:
        projected = to_json_object(failure.constraint)
        if len(dumps_json(projected)) <= _FAILURE_FEEDBACK_PREVIEW_CHARS:
            value["constraint"] = projected
    return value


def _require_turn_ref(ref: str) -> None:
    if (
        not isinstance(ref, str)
        or re.fullmatch(r"session:turn/[a-z0-9_-]+", ref) is None
    ):
        raise SessionContractError("Invalid Session Turn ref")


def _text_preview(value: str) -> str:
    if len(value) <= _TURN_TEXT_PREVIEW_CHARS:
        return value
    return value[: _TURN_TEXT_PREVIEW_CHARS - 3] + "..."
