"""TinySoul loop orchestration module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import (
    CycleSettings,
    LoopSettings,
    TurnSettings,
    parse_loop_settings,
    validate_cycle_task_profiles,
)
from .errors import LoopContractError, LoopError, LoopInvariantError
from .failures import LoopFailureKind
from .outcomes import TurnFailure, TurnOutcomeStatus, TurnOutput
from .signals import (
    SIGNAL_CONTROL_REQUEST,
    SIGNAL_NAMESPACE,
    LoopControlKind,
    LoopControlRequest,
    LoopTraceNoteKind,
    build_control_request_signal,
    consume_control_requests,
    consume_control_signal_requests,
    parse_control_request_signal,
)
from .completion import (
    TurnCompletion,
    TurnCompletionHandler,
    TurnCompletionPipeline,
)
from .preparation import (
    TurnPreparationHandler,
    TurnPreparationPipeline,
    TurnPreparationRequest,
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
        PhaseFailure,
    )
    from .turn import TurnOutcome, TurnRunner

__all__ = [
    "CycleOutcome",
    "CycleRunner",
    "CycleSettings",
    "LoopContractError",
    "LoopControlKind",
    "LoopControlRequest",
    "LoopTraceNoteKind",
    "LoopError",
    "LoopFailureKind",
    "LoopInvariantError",
    "LoopSettings",
    "Phase1Outcome",
    "PhaseFailure",
    "Phase1Unit",
    "Phase2Outcome",
    "Phase2Unit",
    "Phase3Outcome",
    "Phase3Unit",
    "SIGNAL_CONTROL_REQUEST",
    "SIGNAL_NAMESPACE",
    "TurnOutcome",
    "TurnOutcomeStatus",
    "TurnFailure",
    "TurnOutput",
    "TurnPreparationHandler",
    "TurnPreparationPipeline",
    "TurnPreparationRequest",
    "TurnCompletion",
    "TurnCompletionHandler",
    "TurnCompletionPipeline",
    "TurnRunner",
    "TurnSettings",
    "build_control_request_signal",
    "consume_control_requests",
    "consume_control_signal_requests",
    "parse_control_request_signal",
    "parse_loop_settings",
    "validate_cycle_task_profiles",
]


def __getattr__(name: str) -> object:
    if name in {
        "Phase1Outcome",
        "PhaseFailure",
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
            PhaseFailure,
        )

        return {
            "Phase1Outcome": Phase1Outcome,
            "PhaseFailure": PhaseFailure,
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
    raise AttributeError(name)
