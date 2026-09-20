"""Session integration with Turn preparation and completion pipelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from tinysoul.kernel.context.segments import (
    ReadOnlySegmentRegistration,
    SegmentCapability,
    SegmentDescriptor,
    SegmentShape,
    SegmentSlot,
    TurnInfo,
    SegmentReclaim,
)
from tinysoul.kernel.context.errors import (
    ContextInspectFailureReason,
    ContextInspectRequestError,
)
from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.infra.time import CalendarDay
from tinysoul.llm.protocol.messages import Message, UserMessage
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.loop.lifecycle.completion import TurnCompletion
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.plugins.session.runtime_bridge import RuntimeSessionBridge

from .engine import SessionEngine
from .services import SessionService, SessionViewSource
from .errors import SessionError, SessionInspectRequestError
from .records.models import SessionOutputRecord
from .views.background import (
    SessionBackgroundItem,
    SessionBackgroundSnapshot,
    project_map_entry,
)


class SessionSegment:
    """A fixed prior-Turn view with owner-routed progressive inspection."""

    def __init__(
        self,
        source: SessionService,
        snapshot: SessionBackgroundSnapshot,
        day: CalendarDay,
    ) -> None:
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
        return {
            "day": str(self._day),
            "revision": self._snapshot.revision,
            "refs": list(self._snapshot.refs),
        }

    def reclaim(self, required_chars: int) -> SegmentReclaim:
        before = sum(len(dumps_json(item.content)) for item in self._snapshot.items)
        if required_chars <= 0 or before <= self._snapshot.max_chars * 0.8:
            return SegmentReclaim()
        selected = list(self._snapshot.items[1:])

        def projected() -> tuple[SessionBackgroundItem, ...]:
            head = SessionBackgroundItem(
                "session_map",
                project_map_entry(
                    day=str(self._day),
                    total=len(self._snapshot.refs),
                    projected=len(selected),
                ),
            )
            return (head, *selected)

        items = projected()
        after = before
        while selected and after > self._snapshot.max_chars * 0.5:
            selected.pop(0)
            items = projected()
            after = sum(len(dumps_json(item.content)) for item in items)
        self._snapshot = replace(self._snapshot, items=items)
        return SegmentReclaim(max(0, before - after))

    async def inspect(
        self,
        ref: str,
        *,
        query: str | None = None,
        continuation: str | None = None,
    ) -> JsonObject:
        if (
            not ref.startswith("session:map")
            and ref.split("#", 1)[0] not in self._snapshot.refs
        ):
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "Unknown reference in this Session view",
                constraint={"ref": ref},
            )
        try:
            value = await self._source.inspect(
                ref,
                query=query,
                continuation=continuation,
                expected_revision=self._snapshot.revision,
            )
            return value
        except SessionInspectRequestError as exc:
            raise ContextInspectRequestError(
                ContextInspectFailureReason(exc.reason.value),
                str(exc),
                constraint=exc.constraint,
            ) from exc
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc

    async def close(self) -> None:
        pass


class SessionSegmentProvider:
    def __init__(
        self,
        source: SessionService,
        source_day: Callable[[], CalendarDay] | None = None,
    ) -> None:
        self._source = source
        self._source_day = source_day

    async def open(self, info: TurnInfo) -> SessionSegment:
        day = (
            self._source_day()
            if self._source_day is not None
            else CalendarDay(info.day)
        )
        try:
            source = SessionService(await self._source.snapshot_view(day))
            snapshot = await source.background_snapshot(day)
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc
        return SessionSegment(source, snapshot, day)


def session_segment_registration(
    source: SessionService,
    *,
    source_day: Callable[[], CalendarDay] | None = None,
) -> ReadOnlySegmentRegistration:
    return ReadOnlySegmentRegistration(
        descriptor=SegmentDescriptor(
            "session",
            "session",
            SegmentSlot.BACKGROUND,
            20,
            ("session:",),
            SegmentShape.MAP,
            frozenset({
                SegmentCapability.INSPECT,
                SegmentCapability.QUERY,
                SegmentCapability.RECLAIM,
            }),
        ),
        provider=SessionSegmentProvider(source, source_day),
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
        if (
            completion.final_status is TurnOutcomeStatus.ANSWERED
            and completion.output is not None
        ):
            output = SessionOutputRecord(
                text=completion.output.text,
                references=completion.output.references,
            )
        try:
            operations = JoinedOperations()
            await operations.run(
                lambda: self._session.record_turn(
                    completion.context_completion,
                    day=completion.active_day,
                    status=completion.final_status,
                    failure=completion.failure,
                    finish_failures=completion.finish_failures,
                    output=output,
                    exhausted=completion.exhausted,
                )
            )
            operations.check_cancelled()
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
