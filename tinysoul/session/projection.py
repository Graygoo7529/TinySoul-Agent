"""Session integration with Turn preparation and completion pipelines."""

from __future__ import annotations

from tinysoul.context import build_session_sync_signal
from tinysoul.loop.completion import TurnCompletion
from tinysoul.loop.preparation import TurnPreparationRequest
from tinysoul.runtime import Signal
from tinysoul.runtime.bridge import RuntimeSessionBridge

from .engine import SessionEngine
from .errors import SessionError
from .models import SessionOutputRecord


class SessionTurnPreparationHandler:
    def __init__(
        self,
        session: SessionEngine,
        *,
        runtime_bridge: RuntimeSessionBridge | None = None,
    ) -> None:
        self._session = session
        self._runtime_bridge = runtime_bridge or RuntimeSessionBridge()

    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        try:
            snapshot = self._session.background_snapshot(request.business_day)
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
        return (
            build_session_sync_signal(
                snapshot,
                call_id="session_background",
                scope=request.scope,
                source="session.preparation",
            ),
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

    def handle(self, completion: TurnCompletion) -> None:
        output: SessionOutputRecord | None = None
        if completion.output is not None:
            output = SessionOutputRecord(
                text=completion.output.text,
                references=completion.output.references,
            )
        try:
            self._session.record_turn(
                completion.context_completion,
                day=completion.business_day,
                output=output,
                exhausted=completion.exhausted,
            )
        except SessionError as exc:
            raise self._runtime_bridge.from_session_error(exc) from exc
