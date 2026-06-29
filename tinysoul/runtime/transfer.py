"""Runtime transfer outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .scope import RunFrame


class RuntimeTransferAction(StrEnum):
    """Runtime transfer action."""

    RETRY = "retry"
    END = "end"


@dataclass(frozen=True)
class RuntimeTransfer:
    """A transfer decision returned by a trap handler."""

    action: RuntimeTransferAction
    target: RunFrame

    def __post_init__(self) -> None:
        if not isinstance(self.target, RunFrame):
            raise TypeError("RuntimeTransfer.target must be a RunFrame")

    @classmethod
    def retry(cls, target: RunFrame) -> "RuntimeTransfer":
        return cls(action=RuntimeTransferAction.RETRY, target=target)

    @classmethod
    def end(cls, target: RunFrame) -> "RuntimeTransfer":
        return cls(action=RuntimeTransferAction.END, target=target)

    def __str__(self) -> str:
        return f"{self.action.value}({self.target})"
