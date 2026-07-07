"""TinySoul loop orchestration module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import LoopSettings, parse_loop_settings
from .errors import LoopContractError, LoopError, LoopInvariantError
from .failures import LoopFailureKind
from .signals import (
    SIGNAL_CONTROL_REQUEST,
    SIGNAL_NAMESPACE,
    LoopControlKind,
    LoopControlRequest,
    build_control_request_signal,
    consume_control_requests,
    parse_control_request_signal,
)

if TYPE_CHECKING:
    from .app import TinySoulApp, TinySoulAppBuilder
    from .cycle import CycleOutcome, CycleRunner
    from .inputs import InputListener, InputRouter
    from .phases import (
        Phase1Outcome,
        Phase1Unit,
        Phase2Outcome,
        Phase2Unit,
        Phase3Outcome,
        Phase3Unit,
    )
    from .program import ProgramOutcome, ProgramRunner
    from .turn import TurnOutcome, TurnRunner

__all__ = [
    "CycleOutcome",
    "CycleRunner",
    "InputListener",
    "InputRouter",
    "LoopContractError",
    "LoopControlKind",
    "LoopControlRequest",
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
    "ProgramOutcome",
    "ProgramRunner",
    "SIGNAL_CONTROL_REQUEST",
    "SIGNAL_NAMESPACE",
    "TinySoulApp",
    "TinySoulAppBuilder",
    "TurnOutcome",
    "TurnRunner",
    "build_control_request_signal",
    "consume_control_requests",
    "parse_control_request_signal",
    "parse_loop_settings",
]


def __getattr__(name: str) -> object:
    if name in {"TinySoulApp", "TinySoulAppBuilder"}:
        from .app import TinySoulApp, TinySoulAppBuilder

        return {"TinySoulApp": TinySoulApp, "TinySoulAppBuilder": TinySoulAppBuilder}[name]
    if name in {"InputListener", "InputRouter"}:
        from .inputs import InputListener, InputRouter

        return {"InputListener": InputListener, "InputRouter": InputRouter}[name]
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
    if name in {"ProgramOutcome", "ProgramRunner"}:
        from .program import ProgramOutcome, ProgramRunner

        return {"ProgramOutcome": ProgramOutcome, "ProgramRunner": ProgramRunner}[name]
    raise AttributeError(name)
