"""Loop signal protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.runtime import RunScope, Signal, SignalBus

from .errors import LoopContractError

SIGNAL_CONTROL_REQUEST = "loop.control.request"
SIGNAL_NAMESPACE = "loop"


class LoopControlKind(StrEnum):
    """Control requests produced from external input."""

    STOP_TURN = "stop_turn"
    EXIT_PROGRAM = "exit_program"


@dataclass(frozen=True)
class LoopControlRequest:
    """Parsed loop control request."""

    kind: LoopControlKind
    text: str = ""


def build_control_request_signal(
    kind: LoopControlKind,
    *,
    scope: RunScope,
    source: str,
    text: str = "",
) -> Signal:
    return Signal(
        name=SIGNAL_CONTROL_REQUEST,
        source=source,
        scope=scope,
        payload={"kind": kind.value, "text": text},
    )


def parse_control_request_signal(signal: Signal) -> LoopControlRequest:
    if signal.name != SIGNAL_CONTROL_REQUEST:
        raise LoopContractError(f"Unexpected loop signal: {signal.name}")
    value = signal.payload.get("kind")
    if not isinstance(value, str):
        raise LoopContractError("Loop control signal kind must be a string")
    try:
        kind = LoopControlKind(value)
    except ValueError as exc:
        raise LoopContractError(f"Unknown loop control request: {value}") from exc
    text = signal.payload.get("text", "")
    if not isinstance(text, str):
        raise LoopContractError("Loop control signal text must be a string")
    return LoopControlRequest(kind=kind, text=text)


def consume_control_requests(bus: SignalBus) -> tuple[LoopControlRequest, ...]:
    """Consume loop control signals from the bus."""

    signals = bus.consume_name(SIGNAL_CONTROL_REQUEST)
    requests: list[LoopControlRequest] = []
    for signal in signals:
        requests.append(parse_control_request_signal(signal))
    return tuple(requests)
