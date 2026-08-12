"""Application-owned Runtime Generation aggregate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from tinysoul.infra.config import ConfigEnvironment
from tinysoul.infra import InfraSettings
from tinysoul.action.config import ActionSettings
from tinysoul.capabilities import CapabilitiesSettings
from tinysoul.context import ContextSettings
from tinysoul.home import AgentHomeSettings
from tinysoul.llm.config_types import LLMConfig
from tinysoul.loop.config import LoopSettings
from tinysoul.loop.user import UserTurnEntry
from tinysoul.maintenance import MaintenanceEngine, MaintenanceSettings
from tinysoul.memory import MemorySettings
from tinysoul.session import SessionSettings
from tinysoul.workspace import WorkspaceEngine, WorkspaceSettings

from .config import AppSettings
from .inputs import InputCommandParser


@dataclass(frozen=True)
class AppConfigPlan:
    """One validated cross-module settings snapshot for Generation assembly."""

    environment: ConfigEnvironment
    infra: InfraSettings
    app: AppSettings
    action: ActionSettings
    capabilities: CapabilitiesSettings
    context: ContextSettings
    llm: LLMConfig | None
    loop: LoopSettings
    maintenance: MaintenanceSettings
    home: AgentHomeSettings
    memory: MemorySettings
    session: SessionSettings
    workspace: WorkspaceSettings


@dataclass(frozen=True)
class AppRuntimeGeneration:
    """Business objects that are replaced together at an idle boundary."""

    config: ConfigEnvironment
    plan: AppConfigPlan
    user_turn: UserTurnEntry
    maintenance: MaintenanceEngine
    workspace: WorkspaceEngine
    input_parser: InputCommandParser
    app_settings: AppSettings
    maintenance_settings: MaintenanceSettings
    close_callbacks: tuple[Callable[[], None], ...] = field(default_factory=tuple)

    def close(self) -> None:
        """Release explicitly registered generation-owned resources once retired."""

        for callback in reversed(self.close_callbacks):
            try:
                callback()
            except Exception:
                continue
