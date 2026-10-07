"""Session integration with Turn preparation and completion pipelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.context import ContextTurnFacts
from tinysoul.kernel.context.disclosure import DisclosureSearchEntry
from tinysoul.kernel.context.errors import (
    ContextContractError,
    ContextInspectFailureReason,
    ContextInspectRequestError,
)
from tinysoul.kernel.context.segments import (
    ReadOnlySegmentRegistration,
    SegmentCapability,
    SegmentDescriptor,
    SegmentReclaim,
    SegmentRegistration,
    SegmentShape,
    SegmentSlot,
    TurnInfo,
)
from tinysoul.kernel.loop.lifecycle.completion import TurnCompletion
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.kernel.retrieval.disclosure import InspectPage
from tinysoul.llm.protocol.messages import Message, UserMessage
from tinysoul.plugins.session.runtime_bridge import RuntimeSessionBridge
from tinysoul.runtime import Signal

from .engine import SessionEngine
from .errors import SessionError, SessionInspectRequestError
from .records.models import SessionOutputRecord
from .services import SessionOrganizeService, SessionService
from .views import SessionView
from .views.background import (
    SessionBackgroundSnapshot,
)
from .views.navigation import SessionEvidence

SESSION_CONTEXT_UPDATE = "context.session.update"


@dataclass(frozen=True)
class SessionRefresh:
    pass


@dataclass(frozen=True)
class PreparedSession:
    view: SessionView
    background: SessionBackgroundSnapshot


def decode_session_refresh(signal: Signal) -> SessionRefresh:
    if signal.payload != {"refresh": True}:
        raise ContextContractError("Invalid Session refresh")
    return SessionRefresh()


class SessionSegment:
    """A fixed prior-Turn view with owner-routed progressive inspection."""

    def __init__(
        self,
        source: SessionService,
        snapshot: SessionBackgroundSnapshot,
        day: CalendarDay,
        *,
        view: SessionView,
    ) -> None:
        self._source = source
        self._snapshot = snapshot
        self._day = day
        self._view = view

    def render(self) -> tuple[Message, ...]:
        return tuple(
            UserMessage.from_text(item.render(), label=f"session:{item.item_id}")
            for item in self._snapshot.items
        )

    def seal(self) -> JsonObject:
        # References identify the original facts; never copy prior-Turn content.
        return {
            "day": str(self._day),
            "revision": self._snapshot.revision,
            "refs": list(self._snapshot.refs),
        }

    def navigation_refs(self) -> tuple[str, ...]:
        return ("session:map",)

    def reclaim(self, required_chars: int) -> SegmentReclaim:
        before = sum(len(item.render()) for item in self._snapshot.items)
        if required_chars <= 0 or before <= self._snapshot.max_chars * 0.8:
            return SegmentReclaim()
        visible = self._snapshot.items[1:]
        visible_refs = {item.item_id for item in visible}
        navigation = self._snapshot.items[0].content.get("navigation", [])
        assert isinstance(navigation, list)
        prepared = replace(
            self._snapshot,
            candidates=visible,
            navigation=tuple(item for item in navigation if isinstance(item, dict)),
            priority=tuple(
                ref for ref in self._snapshot.priority if ref in visible_refs
            ),
        )
        self._snapshot = prepared.fit(max(512, self._snapshot.budget_chars // 2))
        after = sum(len(item.render()) for item in self._snapshot.items)
        return SegmentReclaim(max(0, before - after))

    async def search_entries(
        self, seed_refs: tuple[str, ...] = ()
    ) -> tuple[DisclosureSearchEntry, ...]:
        operations = JoinedOperations()
        result = await operations.run(lambda: self._view.search_entries(seed_refs))
        operations.check_cancelled()
        return result

    async def inspect(
        self,
        ref: str,
        *,
        query: str | None = None,
        continuation: str | None = None,
    ) -> InspectPage:
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
            view = await self._source.snapshot_view(day)
            source = SessionService(view)
            snapshot = await source.background_snapshot(day)
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc
        return SessionSegment(source, snapshot, day, view=view)


class UpdatingSessionSegment(SessionSegment):
    """A fixed history source with explicitly installed semantic changes."""

    def __init__(
        self,
        source: SessionService,
        snapshot: SessionBackgroundSnapshot,
        day: CalendarDay,
        *,
        view: SessionView,
        writer: SessionOrganizeService,
        facts: Callable[[], ContextTurnFacts],
    ) -> None:
        super().__init__(source, snapshot, day, view=view)
        self._writer, self._facts = writer, facts

    async def prepare(self, updates: tuple[SessionRefresh, ...]) -> PreparedSession:
        evidence = SessionEvidence(self._facts())
        try:
            annotations = await self._writer.annotation_snapshot()
            view = replace(self._view, annotations=annotations, evidence=evidence)
            background = await SessionService(view).background_snapshot(self._day)
            return PreparedSession(view, background.fit(self._snapshot.budget_chars))
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc

    def install(self, prepared: PreparedSession) -> None:
        self._view = prepared.view
        self._source = SessionService(prepared.view)
        self._snapshot = prepared.background


class UpdatingSessionProvider(SessionSegmentProvider):
    def __init__(
        self,
        source: SessionService,
        writer: SessionOrganizeService,
        facts: Callable[[], ContextTurnFacts],
    ) -> None:
        super().__init__(source)
        self._writer, self._facts = writer, facts

    async def open(self, info: TurnInfo) -> UpdatingSessionSegment:
        day = CalendarDay(info.day)
        try:
            view = await self._source.snapshot_view(day)
            source = SessionService(view)
            snapshot = await source.background_snapshot(day)
        except SessionError as exc:
            raise RuntimeSessionBridge().from_session_error(exc) from exc
        return UpdatingSessionSegment(
            source, snapshot, day, view=view, writer=self._writer, facts=self._facts
        )


def session_segment_registration(
    source: SessionService,
    *,
    source_day: Callable[[], CalendarDay] | None = None,
    writer: SessionOrganizeService | None = None,
    facts: Callable[[], ContextTurnFacts] | None = None,
) -> ReadOnlySegmentRegistration | SegmentRegistration[SessionRefresh, PreparedSession]:
    descriptor = SegmentDescriptor(
        "session",
        "session",
        SegmentSlot.BACKGROUND,
        20,
        ("session:",),
        SegmentShape.MAP,
        frozenset(
            {
                SegmentCapability.INSPECT,
                SegmentCapability.QUERY,
                SegmentCapability.SEARCH,
                SegmentCapability.RECLAIM,
            }
        ),
    )
    if writer is not None and facts is not None:
        return SegmentRegistration(
            descriptor,
            UpdatingSessionProvider(source, writer, facts),
            SESSION_CONTEXT_UPDATE,
            SessionRefresh,
            decode_session_refresh,
        )
    return ReadOnlySegmentRegistration(
        descriptor, SessionSegmentProvider(source, source_day)
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
