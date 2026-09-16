"""Typed services exposed by one active Agent generation."""

from __future__ import annotations

from typing import Protocol
from tinysoul.infra.json import JsonObject

from tinysoul.llm.config_types import ProviderCredentialStatus
from tinysoul.plugins.reflection import (ReflectionEngine)
from tinysoul.plugins.workspace import WorkspaceEngine
from .day import DayLifecycle


class UserActionSurface(Protocol):
    def action_catalog(self) -> JsonObject: ...


class AgentRuntimeServices(Protocol):
    """Read-only generation projection consumed by gateway adapters."""

    @property
    def llm_provider_credentials(self) -> tuple[ProviderCredentialStatus, ...]: ...

    @property
    def user_turn(self) -> UserActionSurface: ...

    @property
    def maintenance(self) -> ReflectionEngine: ...

    @property
    def day(self) -> DayLifecycle: ...

    @property
    def workspace(self) -> WorkspaceEngine: ...
