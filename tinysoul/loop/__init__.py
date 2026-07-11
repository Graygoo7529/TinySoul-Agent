"""TinySoul loop orchestration module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import LoopSettings, parse_loop_settings
from .errors import LoopContractError, LoopError, LoopInvariantError
from .failures import LoopFailureKind
from .signals import (
    SIGNAL_CONTROL_REQUEST,
    SIGNAL_TURN_OUTPUT,
    SIGNAL_NAMESPACE,
    LoopControlKind,
    LoopControlRequest,
    LoopTraceNoteKind,
    TurnOutput,
    build_control_request_signal,
    build_turn_output_signal,
    consume_control_requests,
    consume_control_signal_requests,
    consume_turn_outputs,
    parse_control_request_signal,
    parse_turn_output_signal,
)
from .completion import (
    TurnCompletion,
    TurnCompletionHandler,
    TurnCompletionPipeline,
)

if TYPE_CHECKING:
    from .cycle import CycleOutcome, CycleRunner
    from .phases import (
        Phase1Outcome,
        Phase1Unit,
        Phase2Outcome,
        Phase2Unit,
        Phase3Outcome,
        Phase3Unit,
    )
    from .program import ProgramInputEvent, ProgramInputKind, ProgramOutcome, ProgramRunner
    from .turn import TurnOutcome, TurnRunner

__all__ = [
    "CycleOutcome",
    "CycleRunner",
    "LoopContractError",
    "LoopControlKind",
    "LoopControlRequest",
    "LoopTraceNoteKind",
    "LoopError",
    "LoopFailureKind",
    "LoopInvariantError",
    "LoopSettings",
    "Phase1Outcome",
    "Phase1Unit",
    "Phase2Outcome",
    "Phase2Unit",
    "Phase3Outcome",
    "Phase3Unit",
    "ProgramInputEvent",
    "ProgramInputKind",
    "ProgramOutcome",
    "ProgramRunner",
    "SIGNAL_CONTROL_REQUEST",
    "SIGNAL_TURN_OUTPUT",
    "SIGNAL_NAMESPACE",
    "TurnOutcome",
    "TurnOutput",
    "TurnCompletion",
    "TurnCompletionHandler",
    "TurnCompletionPipeline",
    "TurnRunner",
    "build_control_request_signal",
    "build_turn_output_signal",
    "consume_control_requests",
    "consume_control_signal_requests",
    "consume_turn_outputs",
    "parse_control_request_signal",
    "parse_turn_output_signal",
    "parse_loop_settings",
]


def __getattr__(name: str) -> object:
    if name in {
        "Phase1Outcome",
        "Phase1Unit",
        "Phase2Outcome",
        "Phase2Unit",
        "Phase3Outcome",
        "Phase3Unit",
    }:
        from .phases import (
            Phase1Outcome,
            Phase1Unit,
            Phase2Outcome,
            Phase2Unit,
            Phase3Outcome,
            Phase3Unit,
        )

        return {
            "Phase1Outcome": Phase1Outcome,
            "Phase1Unit": Phase1Unit,
            "Phase2Outcome": Phase2Outcome,
            "Phase2Unit": Phase2Unit,
            "Phase3Outcome": Phase3Outcome,
            "Phase3Unit": Phase3Unit,
        }[name]
    if name in {"CycleOutcome", "CycleRunner"}:
        from .cycle import CycleOutcome, CycleRunner

        return {"CycleOutcome": CycleOutcome, "CycleRunner": CycleRunner}[name]
    if name in {"TurnOutcome", "TurnRunner"}:
        from .turn import TurnOutcome, TurnRunner

        return {"TurnOutcome": TurnOutcome, "TurnRunner": TurnRunner}[name]
    if name in {"ProgramInputEvent", "ProgramInputKind", "ProgramOutcome", "ProgramRunner"}:
        from .program import ProgramInputEvent, ProgramInputKind, ProgramOutcome, ProgramRunner

        return {
            "ProgramInputEvent": ProgramInputEvent,
            "ProgramInputKind": ProgramInputKind,
            "ProgramOutcome": ProgramOutcome,
            "ProgramRunner": ProgramRunner,
        }[name]
    raise AttributeError(name)
