"""TinySoul runtime control primitives."""

from .exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    WORKSPACE_TRASH_RESTORE_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from .frame_runner import RuntimeModuleRunner, RuntimeTransferInterrupt
from .errors import (
    RuntimeContractError,
    RuntimeGatewayError,
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
from .generation import (
    RuntimeActivationState,
    RuntimeActivity,
    RuntimeGenerationError,
    RuntimeActivityLease,
    RuntimeGenerationLease,
    RuntimeGenerationSnapshot,
    RuntimeHandle,
    RuntimeWriteLease,
)

__all__ = [
    "CONTEXT_COMPRESSION_REQUIRED",
    "CyclePhase",
    "HOME_RUNTIME_COPY_REQUIRED",
    "WORKSPACE_TRASH_RESTORE_REQUIRED",
    "RUNTIME_CYCLE_END",
    "RUNTIME_PROGRAM_END",
    "RUNTIME_STARTUP_FAILED",
    "RUNTIME_TURN_END",
    "RuntimeException",
    "RuntimeModuleRunner",
    "RuntimeTransferInterrupt",
    "RuntimeContractError",
    "RuntimeGatewayError",
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
    "RuntimeActivationState",
    "RuntimeActivity",
    "RuntimeGenerationError",
    "RuntimeActivityLease",
    "RuntimeGenerationLease",
    "RuntimeGenerationSnapshot",
    "RuntimeHandle",
    "RuntimeWriteLease",
]
