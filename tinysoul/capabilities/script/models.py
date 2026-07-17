"""Script capability domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScriptLanguage(StrEnum):
    PYTHON = "python"
    BASH = "bash"

    @property
    def suffix(self) -> str:
        return ".py" if self is ScriptLanguage.PYTHON else ".sh"


class ScriptJobState(StrEnum):
    RUNNING = "running"
    READY_TO_APPLY = "ready_to_apply"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ScriptSource:
    link: str
    text: str
    digest: str
    language: ScriptLanguage


@dataclass(frozen=True)
class ScriptMutation:
    link: str
    digest: str
    size: int
    state: str
