"""External input routing for loop runners."""

from __future__ import annotations

from collections.abc import Callable
from queue import Queue
import sys
import threading
from typing import TextIO

from tinysoul.context import build_input_append_signal
from tinysoul.runtime import RunLevel, RunScope, SignalBus

from .config import LoopSettings
from .signals import LoopControlKind, build_control_request_signal


class InputRouter:
    """Classify input lines and route them to the queue or signal bus."""

    def __init__(
        self,
        *,
        settings: LoopSettings,
        bus: SignalBus,
        initial_inputs: Queue[str],
        is_turn_active: Callable[[], bool],
        scope_provider: Callable[[], RunScope] | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._initial_inputs = initial_inputs
        self._is_turn_active = is_turn_active
        self._scope_provider = scope_provider or (lambda: RunScope().push(RunLevel.PROGRAM, "program"))

    def route(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        normalized = stripped.lower()
        scope = self._scope_provider()
        if normalized in {command.lower() for command in self._settings.exit_commands}:
            if not self._is_turn_active():
                self._initial_inputs.put(stripped)
                return
            self._bus.emit(
                build_control_request_signal(
                    LoopControlKind.EXIT_PROGRAM,
                    scope=scope,
                    source="loop.inputs",
                    text=stripped,
                )
            )
            return
        if (
            self._is_turn_active()
            and normalized
            in {command.lower() for command in self._settings.stop_turn_commands}
        ):
            self._bus.emit(
                build_control_request_signal(
                    LoopControlKind.STOP_TURN,
                    scope=scope,
                    source="loop.inputs",
                    text=stripped,
                )
            )
            return
        if self._is_turn_active():
            self._bus.emit(
                build_input_append_signal(
                    stripped,
                    scope=scope,
                    source="loop.inputs",
                )
            )
            return
        self._initial_inputs.put(stripped)


class InputListener:
    """Background stdin listener."""

    def __init__(
        self,
        *,
        router: InputRouter,
        stream: TextIO | None = None,
    ) -> None:
        self._router = router
        self._stream = stream or sys.stdin
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="tinysoul-input-listener",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            line = self._stream.readline()
            if line == "":
                self._stop_event.set()
                return
            self._router.route(line)
