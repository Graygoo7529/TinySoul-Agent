"""Session integration with Turn preparation and completion pipelines."""

from __future__ import annotations

from typing import Protocol

from tinysoul.context.segments import ReadOnlySegmentRegistration, SegmentCapability, SegmentDescriptor, SegmentShape, SegmentSlot, TurnInfo
from tinysoul.context.errors import ContextInspectFailureReason, ContextInspectRequestError
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.llm.messages import Message, UserMessage
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.loop.completion import TurnCompletion
from tinysoul.loop.outcomes import TurnOutcomeStatus
from tinysoul.session.runtime_bridge import RuntimeSessionBridge

from .engine import SessionEngine
from .errors import SessionError, SessionInspectRequestError
from .models import SessionOutputRecord
from .background import SessionBackgroundSnapshot


class SessionViewSource(Protocol):
    def background_snapshot(self, day: BusinessDay) -> SessionBackgroundSnapshot: ...

    def inspect(
        self, ref: str | None = None, *, action: str | None = None,
        continuation: str | None = None,
        expected_revision: int | None = None,
    ) -> JsonObject: ...


class SessionSegment:
    """A fixed prior-Turn view with owner-routed progressive inspection."""

    def __init__(self, source: SessionViewSource, snapshot: SessionBackgroundSnapshot, day: BusinessDay) -> None:
        self._source = source
        self._snapshot = snapshot
        self._day = day

    def render(self) -> tuple[Message, ...]:
        return tuple(
            UserMessage.from_json(item.content, label=f"session:{item.item_id}")
            for item in self._snapshot.items
        )

    def seal(self) -> JsonObject:
        # References identify the original facts; never copy prior-Turn content.
        return {"day": str(self._day), "revision": self._snapshot.revision, "refs": list(self._snapshot.refs)}

    async def inspect(self, ref: str, *, continuation: str | None = None) -> JsonObject:
        if ref != "session:map" and ref.split("#", 1)[0] not in self._snapshot.refs:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF, "Unknown reference in this Session view",
                constraint={"ref": ref},
            )
        try:
            operations = JoinedOperations()
            value = await operations.run(lambda: self._source.inspect(
                ref, continuation=continuation, expected_revision=self._snapshot.revision,
            ))
            operations.check_cancelled()
            return value
        except SessionInspectRequestError as exc:
            raise ContextInspectRequestError(
                ContextInspectFailureReason(exc.reason.value), str(exc), constraint=exc.constraint,
            ) from exc
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc

    async def close(self) -> None:
        pass


class SessionSegmentProvider:
    def __init__(self, source: SessionViewSource) -> None:
        self._source = source

    async def open(self, info: TurnInfo) -> SessionSegment:
        day = BusinessDay(info.day)
        try:
            operations = JoinedOperations()
            snapshot = await operations.run(lambda: self._source.background_snapshot(day))
            operations.check_cancelled()
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc
        return SessionSegment(self._source, snapshot, day)


def session_segment_registration(source: SessionViewSource) -> ReadOnlySegmentRegistration:
    return ReadOnlySegmentRegistration(
        descriptor=SegmentDescriptor("session", "session", SegmentSlot.BACKGROUND, 20, ("session:",), SegmentShape.MAP, frozenset({SegmentCapability.INSPECT})),
        provider=SessionSegmentProvider(source),
    )


class SessionTurnCompletionHandler:
    def __init__(
        self,
        session: SessionEngine,
        *,
        runtime_bridge: RuntimeSessionBridge | None = None,
    ) -> None:
        self._session = session
        self._runtime_bridge = runtime_bridge or RuntimeSessionBridge()

    async def handle(self, completion: TurnCompletion) -> None:
        output: SessionOutputRecord | None = None
        if completion.final_status is TurnOutcomeStatus.ANSWERED and completion.output is not None:
            output = SessionOutputRecord(
                text=completion.output.text,
                references=completion.output.references,
            )
        try:
            operations = JoinedOperations()
            await operations.run(lambda: self._session.record_turn(
                completion.context_completion,
                day=completion.business_day,
                status=completion.final_status,
                failure=completion.failure,
                finish_failures=completion.finish_failures,
                output=output,
                exhausted=completion.exhausted,
            ))
            operations.check_cancelled()
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
