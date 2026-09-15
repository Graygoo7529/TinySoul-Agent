"""Process-level application service lifecycle."""

from __future__ import annotations

from typing import Protocol


class AppService(Protocol):
    """Long-lived service managed by TinySoulApp."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
