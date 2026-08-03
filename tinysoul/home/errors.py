"""Agent Home module errors."""

from __future__ import annotations

from pathlib import Path

from tinysoul.infra.json import JsonObject


class AgentHomeError(Exception):
    """Base class for Agent Home module errors."""


class AgentHomeContractError(AgentHomeError):
    """Raised when callers violate Agent Home contracts."""


class AgentHomeInvariantError(AgentHomeError):
    """Raised when Agent Home internal invariants are broken."""


class AgentHomeIOError(AgentHomeError):
    """Raised when Agent Home filesystem operations fail at the module boundary."""


class AgentHomeRuntimeCopyRequired(AgentHomeError):
    """Raised when a home link must be copied into runtime home before reading."""

    def __init__(self, link: str, *, source_path: Path, runtime_path: Path) -> None:
        super().__init__(f"Agent Home runtime copy is required: {link}")
        self.link = link
        self.source_path = source_path
        self.runtime_path = runtime_path

    def to_payload(self) -> JsonObject:
        return {
            "link": self.link,
            "source_path": str(self.source_path),
            "runtime_path": str(self.runtime_path),
            "error_type": type(self).__name__,
        }
