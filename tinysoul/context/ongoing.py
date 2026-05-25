"""Runtime controls for ONGOING action executions."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Callable

from tinysoul.action.framework.run_config import TerminationReason


@dataclass
class OngoingControl:
    """Termination control for one ONGOING execution."""

    execution_id: str
    action_name: str
    terminate_event: threading.Event = field(default_factory=threading.Event)
    termination_reason: TerminationReason | None = None
    terminate_callback: Callable[[TerminationReason], None] | None = None

    def request_termination(self, reason: TerminationReason) -> None:
        if self.termination_reason is None:
            self.termination_reason = reason
        self.terminate_event.set()
        if self.terminate_callback is not None:
            self.terminate_callback(reason)

    def is_termination_requested(self) -> bool:
        return self.terminate_event.is_set()


class OngoingControlRegistry:
    """In-memory registry for runtime ONGOING controls."""

    def __init__(self) -> None:
        self._controls: dict[str, OngoingControl] = {}
        self._lock = threading.Lock()

    def register(self, control: OngoingControl) -> None:
        with self._lock:
            self._controls[control.execution_id] = control

    def get(self, execution_id: str) -> OngoingControl | None:
        with self._lock:
            return self._controls.get(execution_id)

    def request_termination(
        self,
        execution_id: str,
        reason: TerminationReason,
    ) -> bool:
        control = self.get(execution_id)
        if control is None:
            return False
        control.request_termination(reason)
        return True

    def request_all_termination(self, reason: TerminationReason) -> int:
        """Request termination for all currently registered controls."""
        with self._lock:
            controls = list(self._controls.values())
        for control in controls:
            control.request_termination(reason)
        return len(controls)

    def unregister(self, execution_id: str) -> OngoingControl | None:
        with self._lock:
            return self._controls.pop(execution_id, None)
