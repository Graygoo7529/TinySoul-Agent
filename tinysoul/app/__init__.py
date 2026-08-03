"""TinySoul application assembly and typed request ingress."""

from .builder import TinySoulAppBuilder
from .config import AppSettings, InputCommandSettings, OutputSettings, parse_app_settings
from .errors import (
    AppContractError,
    AppError,
    AppInitializationError,
    AppInstanceError,
    AppInvariantError,
    AppOutputError,
)
from .failures import AppFailureKind
from .gateway import AppCommandGateway
from .initializer import (
    ProjectConfigProfile,
    ProjectInitializationOutcome,
    ProjectInitializer,
    ProjectResetOutcome,
    ProjectResetter,
)
from .inputs import (
    CommandReceipt,
    InputCommandParser,
    InputDispatcher,
    InputEvent,
    InputIntent,
    InputIntentKind,
    InputSink,
    InputSource,
)
from .instance import (
    AppInstanceIdentity,
    ProjectInstanceLease,
    instance_directory,
    project_identity_for,
)
from .outputs import ConsoleOutputSink, ObservationRoute, ObservationRouter, OutputSink
from .requests import AppRequest, ExitRequest, UserTurnRequest
from .runtime import TinySoulApp
from .services import AppService
from .sources import MaintenanceScheduler, TerminalInputSource

__all__ = [
    "AppCommandGateway",
    "AppContractError",
    "AppError",
    "AppFailureKind",
    "AppInitializationError",
    "AppInstanceIdentity",
    "AppInstanceError",
    "AppInvariantError",
    "AppOutputError",
    "AppRequest",
    "AppService",
    "AppSettings",
    "CommandReceipt",
    "ConsoleOutputSink",
    "ExitRequest",
    "InputCommandParser",
    "InputCommandSettings",
    "InputDispatcher",
    "InputEvent",
    "InputIntent",
    "InputIntentKind",
    "InputSink",
    "InputSource",
    "MaintenanceScheduler",
    "ObservationRoute",
    "ObservationRouter",
    "OutputSettings",
    "OutputSink",
    "ProjectConfigProfile",
    "ProjectInitializationOutcome",
    "ProjectInitializer",
    "ProjectInstanceLease",
    "ProjectResetOutcome",
    "ProjectResetter",
    "TerminalInputSource",
    "TinySoulApp",
    "TinySoulAppBuilder",
    "UserTurnRequest",
    "instance_directory",
    "parse_app_settings",
    "project_identity_for",
]
