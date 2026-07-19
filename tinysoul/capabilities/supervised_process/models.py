"""Owner-neutral supervised process domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from tinysoul.action.backends import ManagedProcessRequest
from tinysoul.infra import JsonObject
from tinysoul.workspace import WorkspaceManifest, WorkspaceMirror


class SupervisedProcessOwner(StrEnum):
    SCRIPT = "script"
    SHELL = "shell"


class SupervisedProcessState(StrEnum):
    RUNNING = "running"
    READY_TO_APPLY = "ready_to_apply"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    STOPPED = "stopped"


class SupervisedProcessPreparer(Protocol):
    def __call__(
        self,
        staging_root: Path,
        mirror: WorkspaceMirror,
    ) -> ManagedProcessRequest: ...


@dataclass(frozen=True)
class SupervisedProcessObservation:
    payload: JsonObject
    timed_out: bool = False
    failed: bool = False


@dataclass(frozen=True)
class SupervisedProcessApply:
    payload: JsonObject
    manifest: WorkspaceManifest
