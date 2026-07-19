"""TinySoul runtime control primitives."""

from .exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    WORKSPACE_TRASH_RESTORE_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RUNTIME_TURN_OUTPUT,
    RuntimeException,
)
from .frame_runner import RuntimeModuleRunner, RuntimeTransferInterrupt
from .errors import (
    RuntimeContractError,
    RuntimeGatewayError,
    RuntimeInputBlockedError,
    RuntimeInvariantError,
    RuntimeModuleError,
)
from .scope import CyclePhase, RunFrame, RunLevel, RunScope
from .observation import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    emit_observation,
    observation_enabled,
)
from .transfer import RuntimeTransfer, RuntimeTransferAction
from .trap import TrapHandler, TrapHandlerRegistry, TrapResult, TrapSnap, RuntimeTrap
from .signals import Signal, SignalBus, SignalWatch

__all__ = [
    "CONTEXT_COMPRESSION_REQUIRED",
    "CyclePhase",
    "HOME_RUNTIME_COPY_REQUIRED",
    "WORKSPACE_TRASH_RESTORE_REQUIRED",
    "RUNTIME_CYCLE_END",
    "RUNTIME_PROGRAM_END",
    "RUNTIME_STARTUP_FAILED",
    "RUNTIME_TURN_END",
    "RUNTIME_TURN_OUTPUT",
    "RuntimeException",
    "RuntimeModuleRunner",
    "RuntimeTransferInterrupt",
    "RuntimeContractError",
    "RuntimeGatewayError",
    "RuntimeInputBlockedError",
    "RuntimeInvariantError",
    "RuntimeModuleError",
    "NullObservationEmitter",
    "ObservationEmitter",
    "ObservationEvent",
    "ObservationLevel",
    "emit_observation",
    "observation_enabled",
    "RunFrame",
    "RunLevel",
    "RunScope",
    "RuntimeTransfer",
    "RuntimeTransferAction",
    "RuntimeTrap",
    "Signal",
    "SignalBus",
    "SignalWatch",
    "TrapHandler",
    "TrapHandlerRegistry",
    "TrapResult",
    "TrapSnap",
]
