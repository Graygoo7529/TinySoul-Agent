"""Loop signal protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import RunScope, Signal, SignalBus

from .errors import LoopContractError

SIGNAL_CONTROL_REQUEST = "loop.control.request"
SIGNAL_TURN_OUTPUT = "loop.turn.output"
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


@dataclass(frozen=True)
class TurnOutput:
    """Validated user-facing output produced by a completed Turn."""

    text: str
    result_id: str
    references: tuple[str, ...] = ()
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text:
            raise LoopContractError("TurnOutput.text must be non-empty")
        if not self.result_id:
            raise LoopContractError("TurnOutput.result_id must be non-empty")
        for reference in self.references:
            if not isinstance(reference, str) or not reference:
                raise LoopContractError(
                    "TurnOutput.references must contain non-empty strings"
                )
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


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

    return tuple(
        request
        for _, request in consume_control_signal_requests(bus)
    )


def consume_control_signal_requests(
    bus: SignalBus,
) -> tuple[tuple[Signal, LoopControlRequest], ...]:
    """Consume control requests while preserving their runtime scope envelopes."""

    return tuple(
        (signal, parse_control_request_signal(signal))
        for signal in bus.consume_name(SIGNAL_CONTROL_REQUEST)
    )


def build_turn_output_signal(
    output: TurnOutput,
    *,
    scope: RunScope,
    source: str,
) -> Signal:
    return Signal(
        name=SIGNAL_TURN_OUTPUT,
        source=source,
        scope=scope,
        payload={
            "text": output.text,
            "result_id": output.result_id,
            "references": list(output.references),
            "metadata": output.metadata,
        },
    )


def parse_turn_output_signal(signal: Signal) -> TurnOutput:
    if signal.name != SIGNAL_TURN_OUTPUT:
        raise LoopContractError(f"Unexpected Turn output signal: {signal.name}")
    text = signal.payload.get("text")
    result_id = signal.payload.get("result_id")
    references_value = signal.payload.get("references", [])
    metadata = signal.payload.get("metadata", {})
    if not isinstance(text, str) or not text:
        raise LoopContractError("Turn output signal requires non-empty text")
    if not isinstance(result_id, str) or not result_id:
        raise LoopContractError("Turn output signal requires non-empty result_id")
    if not isinstance(references_value, list):
        raise LoopContractError("Turn output signal references must be a string list")
    references: list[str] = []
    for item in references_value:
        if not isinstance(item, str) or not item:
            raise LoopContractError(
                "Turn output signal references must contain non-empty strings"
            )
        references.append(item)
    if not isinstance(metadata, dict):
        raise LoopContractError("Turn output signal metadata must be an object")
    return TurnOutput(
        text=text,
        result_id=result_id,
        references=tuple(references),
        metadata=to_json_object(metadata),
    )


def consume_turn_outputs(bus: SignalBus) -> tuple[tuple[Signal, TurnOutput], ...]:
    """Consume validated Turn output signals with their runtime envelopes."""

    return tuple(
        (signal, parse_turn_output_signal(signal))
        for signal in bus.consume_name(SIGNAL_TURN_OUTPUT)
    )
