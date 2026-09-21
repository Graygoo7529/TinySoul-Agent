"""One factual interaction projection shared by Background and inspection."""

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.kernel.context.builtin.trace import TraceFactKind
from ..errors import SessionInvariantError
from ..records.models import SessionActionOutcome, SessionTurnRecord
from .navigation import action_leaf_ref, input_ref, resource_locator


class InteractionRole(StrEnum):
    INPUT = "user.input"
    APPEND = "user.append"
    REPLY = "user.reply"
    QUESTION = "agent.question"
    REASON = "agent.reason"
    ACTION = "agent.action"
    OUTPUT = "agent.output"


@dataclass(frozen=True)
class SessionInteraction:
    role: InteractionRole
    ref: str
    content: JsonObject

    def __post_init__(self) -> None:
        if not isinstance(self.role, InteractionRole) or not self.ref:
            raise SessionInvariantError(
                "Interaction requires a role and fact reference"
            )

    def to_json(self) -> JsonObject:
        return {
            "kind": "interaction",
            "role": self.role.value,
            "ref": self.ref,
            **self.content,
        }


def project_interactions(record: SessionTurnRecord) -> tuple[SessionInteraction, ...]:
    """Collapse observation milestones, retaining fact order and question identity."""
    questions = {
        item.result_id: action_leaf_ref(record.ref, index)
        for index, item in enumerate(record.actions)
        if item.action == "core.ask" and item.outcome is SessionActionOutcome.SUCCESS
    }
    positions: dict[tuple[str, TraceFactKind], int] = {}
    for index, fact in enumerate(record.timeline):
        positions.setdefault((fact.ref, fact.kind), index)
    ordered: list[tuple[int, int, SessionInteraction]] = []

    def add(
        item: SessionInteraction, kinds: tuple[TraceFactKind, ...], fallback: int
    ) -> None:
        position = next(
            (
                positions[(item.ref, kind)]
                for kind in kinds
                if (item.ref, kind) in positions
            ),
            len(record.timeline) + fallback,
        )
        ordered.append((position, len(ordered), item))

    for index, item in enumerate(record.inputs):
        role = (
            InteractionRole.REPLY
            if item.reply_to
            else (InteractionRole.INPUT if index == 0 else InteractionRole.APPEND)
        )
        content: JsonObject = {"text": item.text}
        if item.reply_to:
            content["reply_to"] = questions[item.reply_to]
        add(
            SessionInteraction(role, input_ref(record.ref, index), content),
            (TraceFactKind.INPUT_VISIBLE, TraceFactKind.INPUT_INSTALLED),
            index,
        )
    for index, action in enumerate(record.actions):
        ref = action_leaf_ref(record.ref, index)
        if action.action == "core.answer":
            continue
        content = {"action": action.action, "outcome": action.outcome.value}
        role = InteractionRole.ACTION
        anchor = (TraceFactKind.ACTION_STARTED, TraceFactKind.ACTION_REQUESTED)
        if (
            action.action == "core.ask"
            and action.outcome is SessionActionOutcome.SUCCESS
        ):
            role = InteractionRole.QUESTION
            text, options = action.result.get("text"), action.result.get("options", [])
            if (
                not isinstance(text, str)
                or not isinstance(options, list)
                or any(not isinstance(item, str) for item in options)
            ):
                raise SessionInvariantError(
                    "Stored question has invalid canonical content"
                )
            content.update(text=text, options=options)
            content["answered"] = any(
                item.reply_to == action.result_id for item in record.inputs
            )
            anchor = (TraceFactKind.ACTION_SETTLED, *anchor)
        elif action.action == "core.reason":
            role = InteractionRole.REASON
        if action.failure is not None:
            content["failure"] = {
                "reason": action.failure.reason,
                "feedback": action.failure.feedback[:240],
            }
        if action.references:
            content["references"] = [
                resource_locator(record, link) for link in action.references
            ]
        add(SessionInteraction(role, ref, content), anchor, len(record.inputs) + index)
    ordered.sort(key=lambda item: (item[0], item[1]))
    result = tuple(item for _, _, item in ordered)
    if record.output is not None:
        result += (
            SessionInteraction(
                InteractionRole.OUTPUT,
                f"{record.ref}#output",
                {
                    "text": record.output.text,
                    "references": [
                        resource_locator(record, link)
                        for link in record.output.references
                    ],
                },
            ),
        )
    return result


def interaction_header(record: SessionTurnRecord) -> JsonObject:
    value: JsonObject = {
        "kind": "session_turn",
        "ref": record.ref,
        "day": record.day,
        "status": record.status.value,
    }
    failures = ((record.failure,) if record.failure else ()) + record.finish_failures
    if failures:
        value["failures"] = [
            {"kind": item.kind, "message": item.message[:240]} for item in failures
        ]
    return value
