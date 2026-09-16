"""Runtime transfer outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import RuntimeContractError
from .scope import RunFrame, RunLevel


class RuntimeTransferAction(StrEnum):
    """Runtime transfer action."""

    RETRY = "retry"
    END = "end"
    SUSPEND = "suspend"


@dataclass(frozen=True)
class RuntimeTransfer:
    """A transfer decision returned by a trap handler."""

    action: RuntimeTransferAction
    target: RunFrame

    def __post_init__(self) -> None:
        if not isinstance(self.action, RuntimeTransferAction):
            raise RuntimeContractError("RuntimeTransfer.action is invalid")
        if not isinstance(self.target, RunFrame):
            raise RuntimeContractError("RuntimeTransfer.target must be a RunFrame")
        if self.action is RuntimeTransferAction.SUSPEND and self.target.level is not RunLevel.TURN:
            raise RuntimeContractError("Only a Turn frame can be suspended")

    @classmethod
    def retry(cls, target: RunFrame) -> "RuntimeTransfer":
        return cls(action=RuntimeTransferAction.RETRY, target=target)

    @classmethod
    def end(cls, target: RunFrame) -> "RuntimeTransfer":
        return cls(action=RuntimeTransferAction.END, target=target)

    @classmethod
    def suspend(cls, target: RunFrame) -> "RuntimeTransfer":
        return cls(action=RuntimeTransferAction.SUSPEND, target=target)

    def __str__(self) -> str:
        return f"{self.action.value}({self.target})"
