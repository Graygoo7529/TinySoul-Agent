"""TinySoul runtime control primitives."""

from .exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    HOME_RUNTIME_COPY_REQUIRED,
    LLM_MODEL_CHAIN_EXHAUSTED,
    PROGRAM_END_REQUESTED,
    RUNTIME_CYCLE_END_REQUESTED,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END_REQUESTED,
    RUNTIME_UNHANDLED_FAILURE,
    RuntimeException,
)
from .scope import RunFrame, RunLevel, RunScope
from .transfer import RuntimeTransfer, RuntimeTransferAction
from .trap import TrapHandler, TrapHandlerRegistry, TrapResult, TrapSnap, RuntimeTrap
from .signals import Signal, SignalBus, SignalHandler, SignalHandlerRegistry

__all__ = [
    "CONTEXT_COMPRESSION_REQUIRED",
    "HOME_RUNTIME_COPY_REQUIRED",
    "LLM_MODEL_CHAIN_EXHAUSTED",
    "PROGRAM_END_REQUESTED",
    "RUNTIME_CYCLE_END_REQUESTED",
    "RUNTIME_STARTUP_FAILED",
    "RUNTIME_TURN_END_REQUESTED",
    "RUNTIME_UNHANDLED_FAILURE",
    "RuntimeException",
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
