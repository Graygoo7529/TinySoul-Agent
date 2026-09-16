"""Process-level application service lifecycle."""

from __future__ import annotations

from typing import Protocol


class EnvironmentService(Protocol):
    """Long-lived service managed by AgentAssembly."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
