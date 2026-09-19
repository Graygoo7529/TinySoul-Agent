"""Explicit execution adapters over shared Job supervision."""

from .backend import ProcessJobBackend
from .config import (
    ExecutionSettings,
    Interpreter,
    InterpreterSpec,
    parse_execution_settings,
)

__all__ = [
    "ExecutionSettings",
    "Interpreter",
    "InterpreterSpec",
    "ProcessJobBackend",
    "parse_execution_settings",
]
