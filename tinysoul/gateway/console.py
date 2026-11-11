"""Small process monitor; model details belong to Endpoint and Trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import sys
from threading import RLock
from time import time
from typing import TextIO

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationEvent, ObservationLevel, RunLevel
from .errors import ConsoleOutputError


class ConsoleMode(StrEnum):
    QUIET = "quiet"
    DETAIL = "detail"


@dataclass
class ConsoleMonitor:
    """Select short summaries without keeping or modifying business events."""

    mode: ConsoleMode = ConsoleMode.QUIET
    stream: TextIO = field(default_factory=lambda: sys.stderr)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _failure: CleanupDiagnostic | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ConsoleMode):
            raise ConsoleOutputError("Console mode must be quiet or detail")

    @property
    def failure(self) -> CleanupDiagnostic | None:
        return self._failure

    def report(self, summary: str) -> None:
        """Render a gateway-owned lifecycle summary through the same sink."""
        self._write(summary, time())

    def write(self, event: ObservationEvent) -> None:
        summary = _render(event, self.mode)
        if summary is None:
            return
        scope = " ".join(
            _short(frame.name)
            for frame in event.scope
            if frame.level in {RunLevel.TURN, RunLevel.CYCLE, RunLevel.PHASE}
        )
        self._write(f"{scope}  {summary}" if scope else summary, event.created_at)

    def _write(self, summary: str, created_at: float) -> None:
        with self._lock:
            if self._failure is not None:
                return
            stamp = datetime.fromtimestamp(created_at).strftime("%H:%M:%S")
            try:
                self.stream.write(f"{stamp}  {_short(summary, 640)}\n")
                self.stream.flush()
            except (OSError, ValueError) as exc:
                self._failure = CleanupDiagnostic("console", type(exc).__name__)


def _short(value: str, limit: int = 120) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _fields(payload: JsonObject, *keys: str) -> str:
    return " ".join(
        f"{key}={_short(str(value))}"
        for key in keys
        if isinstance(value := payload.get(key), (str, int, float, bool))
        and value != ""
    )


def _render(event: ObservationEvent, mode: ConsoleMode) -> str | None:
    if event.level is ObservationLevel.MODEL:
        return None
    name, payload = event.name, event.payload
    detail = mode is ConsoleMode.DETAIL
    match name:
        case "runtime.source_status":
            return f"source {_short(event.source)} {_fields(payload, 'state', 'error_type')}"
        case "turn.failed":
            return f"turn failed {_fields(payload, 'module', 'kind', 'reason')}"
        case "config.activation.completed" | "config.activation.failed" | "config.activation.cleanup.failed":
            return f"config {name.removeprefix('config.activation.')} {_fields(payload, 'resource', 'error_type')}"
        case "daily.transition.completed" | "daily.transition.recovered" | "daily.transition.failed":
            return f"day {name.removeprefix('daily.transition.')} {_fields(payload, 'from_day', 'to_day', 'target_day', 'error_type')}"
        case "runtime.trap":
            if detail or event.source == "agent.program":
                return f"transition {_fields(payload, 'reason', 'transfer_action', 'transfer_target')}"
        case "reflection.completed":
            if detail or payload.get("status") in {"failed", "partial"}:
                return f"reflection {_fields(payload, 'request_id', 'status', 'active_day')}"
        case "reflection.started" if detail:
            request = payload.get("request")
            fields = _fields(request, 'scope', 'target_day', 'request_id') if isinstance(request, dict) else ""
            return f"reflection started {fields}"
        case "turn.completed" if detail:
            if payload.get("status") != "failed":
                return f"turn {_fields(payload, 'status')}"
        case "turn.started" if detail:
            return f"turn started {_fields(payload, 'request_id', 'input_source')}"
        case "turn.question" if detail:
            return f"turn waiting for reply {_fields(payload, 'question_id')}"
        case "turn.budget_requested" if detail:
            return f"turn waiting for budget {_fields(payload, 'request_id', 'next_cycle_index')}"
        case "loop.phase.started" | "loop.phase.completed" if detail:
            fields = _fields(payload, 'failed', 'cancelled', 'ended')
            failure = payload.get("failure")
            reason = _fields(failure, 'reason') if isinstance(failure, dict) else ""
            return f"phase {name.rsplit('.', 1)[-1]} {fields} {reason}"
        case "action.call" if detail:
            return f"action prepared {_fields(payload, 'action', 'call_id')}"
        case "action.result" if detail:
            return f"action result {_fields(payload, 'action', 'status', 'invoke_id')}"
        case "action.execution" if detail:
            if payload.get("state") in {"started", "cancelled", "not_executed", "unknown"}:
                return f"action {_fields(payload, 'invoke_id', 'state')}"
        case "llm.task.started" | "llm.task.completed" | "llm.task.failed" | "llm.provider.retry" if detail:
            return f"{name} {_fields(payload, 'task_id', 'profile', 'model_id', 'provider_id', 'attempt', 'status', 'reason', 'error_type')}"
        case "model.call.started" | "model.call.completed" | "model.call.failed" | "model.call.cancelled" | "model.call.retry" if detail:
            return f"{name} {_fields(payload, 'call_id', 'consumer', 'model', 'provider', 'attempt', 'elapsed_seconds', 'status')}"
        case "config.activation.started" | "daily.transition.started" | "program.started" | "program.completed" if detail:
            return f"{name} {_fields(payload, 'from_day', 'to_day', 'turn_count', 'reflection_count')}"
    return None
