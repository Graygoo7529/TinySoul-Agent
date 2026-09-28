"""One factual interaction projection shared by Background and inspection."""

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.kernel.context import ContextTurnFacts
from tinysoul.kernel.context.builtin.trace import TraceFactKind
from tinysoul.kernel.interaction import QuestionContent, QuestionError

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
            "id": self.ref,
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
        ref = input_ref(record.ref, index)
        visible = (ref, TraceFactKind.INPUT_VISIBLE) in positions
        content: JsonObject = {
            "text": item.text,
            "delivery": "visible" if visible else "installed",
        }
        if item.reply_to:
            content["reply_to"] = questions[item.reply_to]
            content["question_id"] = item.reply_to
        if item.answer is not None:
            content["answer"] = item.answer.to_json()
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
            try:
                content.update(QuestionContent.from_json(action.result).to_json())
            except QuestionError as exc:
                raise SessionInvariantError(
                    "Stored question has invalid canonical content"
                ) from exc
            if "legacy_options" in action.result:
                content.update(
                    legacy_options=action.result["legacy_options"], legacy=True
                )
            content["question_id"] = action.result_id
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


def project_current_interactions(
    facts: ContextTurnFacts,
) -> tuple[SessionInteraction, ...]:
    """Use original Trace identities and order; never manufacture a completed record."""
    root = f"turn:trace@{facts.turn_id}"
    positions = {item.ref: item.sequence for item in reversed(facts.timeline)}
    settled = {
        item.ref: item.sequence
        for item in facts.timeline
        if item.kind is TraceFactKind.ACTION_SETTLED
    }
    visible = {
        item.ref for item in facts.timeline if item.kind is TraceFactKind.INPUT_VISIBLE
    }
    items: list[SessionInteraction] = []
    for index, item in enumerate(facts.inputs):
        ref = f"{root}#input/{item.input_id}"
        role = (
            InteractionRole.REPLY
            if item.reply_to
            else InteractionRole.INPUT
            if index == 0
            else InteractionRole.APPEND
        )
        content: JsonObject = {
            "id": item.input_id,
            "text": item.text,
            "delivery": "visible" if ref in visible else "installed",
        }
        if item.reply_to:
            content["question_id"] = item.reply_to
        if item.answer:
            content["answer"] = item.answer.to_json()
        items.append(SessionInteraction(role, ref, content))
    for index, fact in enumerate(facts.actions):
        action, result = fact.call.action_name, fact.result
        ref = f"{root}#action/{index}"
        role = (
            InteractionRole.REASON
            if action == "core.reason"
            else InteractionRole.ACTION
        )
        content = {
            "id": fact.invoke_id or fact.call.call_id,
            "action": action,
            "state": fact.state.value,
            "call_id": fact.call.call_id,
            "invoke_id": fact.invoke_id,
        }
        if result is not None:
            content["outcome"] = result.status.value
            content["result"] = (
                result.trace_projection.canonical_payload
                if result.trace_projection
                else result.payload
            )
            if action == "core.ask" and result.status.value == "success":
                role = InteractionRole.QUESTION
                content.update(QuestionContent.from_json(result.payload).to_json())
                content["question_id"] = result.result_id
                content["answered"] = any(
                    item.reply_to == result.result_id for item in facts.inputs
                )
                positions[ref] = settled.get(
                    ref, positions.get(ref, len(facts.timeline))
                )
            elif action == "core.answer" and result.status.value == "success":
                role = InteractionRole.OUTPUT
                content.update(result.payload)
        items.append(SessionInteraction(role, ref, content))
    return tuple(
        sorted(items, key=lambda item: positions.get(item.ref, len(facts.timeline) + 1))
    )
