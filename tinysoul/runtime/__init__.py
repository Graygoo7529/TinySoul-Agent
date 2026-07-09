"""TinySoul runtime control primitives."""

from .exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from .errors import RuntimeContractError, RuntimeInvariantError, RuntimeModuleError
from .scope import CyclePhase, RunFrame, RunLevel, RunScope
from .transfer import RuntimeTransfer, RuntimeTransferAction
from .trap import TrapHandler, TrapHandlerRegistry, TrapResult, TrapSnap, RuntimeTrap
from .signals import Signal, SignalBus, SignalHandler, SignalHandlerRegistry

__all__ = [
    "CONTEXT_COMPRESSION_REQUIRED",
    "CyclePhase",
    "HOME_RUNTIME_COPY_REQUIRED",
    "RUNTIME_CYCLE_END",
    "RUNTIME_PROGRAM_END",
    "RUNTIME_STARTUP_FAILED",
    "RUNTIME_TURN_END",
    "RuntimeException",
    "RuntimeContractError",
    "RuntimeInvariantError",
    "RuntimeModuleError",
    "RunFrame",
    "RunLevel",
    "RunScope",
    "RuntimeTransfer",
    "RuntimeTransferAction",
    "RuntimeTrap",
    "Signal",
    "SignalBus",
    "SignalHandler",
    "SignalHandlerRegistry",
    "TrapHandler",
    "TrapHandlerRegistry",
    "TrapResult",
    "TrapSnap",
]
