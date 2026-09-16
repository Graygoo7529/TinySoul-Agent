"""Immediate Shell capability domain objects."""

from enum import StrEnum


class ShellInterpreter(StrEnum):
    POWERSHELL = "powershell"
    CMD = "cmd"
    BASH = "bash"
