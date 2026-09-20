"""TinySoul runtime control primitives."""

from .control.exception import (
    RUNTIME_CYCLE_END,
    RUNTIME_AGENT_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from .control.frame_runner import RuntimeModuleRunner, RuntimeTransferInterrupt
from .errors import (
    RuntimeContractError,
    RuntimeGatewayError,
    RuntimeInvariantError,
    RuntimeModuleError,
)
from .control.scope import CyclePhase, RunFrame, RunLevel, RunScope
from .observation import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    emit_observation,
    observation_enabled,
)
from .control.transfer import RuntimeTransfer, RuntimeTransferAction
from .trap import TrapHandler, TrapHandlerRegistry, TrapResult, TrapSnap, RuntimeTrap
from .signals import Signal, SignalBus
from .events import (
    EnvironmentEvent,
    EventBus,
    EventCapacityError,
    EventKind,
    EventProtocolError,
    EventReceipt,
    EventFilter,
)
from .sources import EventSink, RuntimeSource, SourceState, SourceStatus
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
    "CyclePhase",
    "RUNTIME_CYCLE_END",
    "RUNTIME_AGENT_END",
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
    "EnvironmentEvent",
    "EventBus",
    "EventCapacityError",
    "EventKind",
    "EventProtocolError",
    "EventReceipt",
    "EventFilter",
    "EventSink",
    "RuntimeSource",
    "SourceState",
    "SourceStatus",
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
