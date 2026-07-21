"""TinySoul application assembly layer."""

from .builder import TinySoulAppBuilder
from .config import (
    AppSettings,
    InputCommandSettings,
    OutputSettings,
    SchedulerSettings,
    parse_app_settings,
)
from .errors import (
    AppContractError,
    AppError,
    AppInitializationError,
    AppInstanceError,
    AppInvariantError,
    AppOutputError,
)
from .gateway import AppCommandGateway
from .initializer import (
    ProjectConfigProfile,
    ProjectInitializationOutcome,
    ProjectInitializer,
)
from .instance import (
    AppInstanceIdentity,
    ProjectInstanceLease,
    instance_directory,
    project_identity_for,
)
from .failures import AppFailureKind
from .inputs import (
    CommandReceipt,
    InputCommandParser,
    InputDispatcher,
    InputEvent,
    InputIntent,
    InputIntentKind,
    InputSink,
    InputSource,
    MaintenanceRequestKind,
)
from .outputs import ConsoleOutputSink, ObservationRoute, ObservationRouter, OutputSink
from .maintenance import HomeDecisionBroker, MaintenanceDecisionSnapshot
from .runtime import TinySoulApp
from .services import AppService
from .sources import MaintenanceSchedule, MaintenanceScheduler, TerminalInputSource

__all__ = [
    "AppContractError",
    "AppError",
    "AppFailureKind",
    "AppInitializationError",
    "AppInstanceError",
    "AppInstanceIdentity",
    "AppInvariantError",
    "AppOutputError",
    "AppSettings",
    "AppCommandGateway",
    "AppService",
    "ConsoleOutputSink",
    "CommandReceipt",
    "InputCommandParser",
    "InputCommandSettings",
    "InputDispatcher",
    "InputEvent",
    "InputIntent",
    "InputIntentKind",
    "InputSink",
    "InputSource",
    "MaintenanceRequestKind",
    "ObservationRouter",
    "ObservationRoute",
    "OutputSettings",
    "OutputSink",
    "ProjectInitializationOutcome",
    "ProjectConfigProfile",
    "ProjectInitializer",
    "ProjectInstanceLease",
    "TerminalInputSource",
    "HomeDecisionBroker",
    "MaintenanceDecisionSnapshot",
    "MaintenanceSchedule",
    "MaintenanceScheduler",
    "SchedulerSettings",
    "TinySoulApp",
    "TinySoulAppBuilder",
    "parse_app_settings",
    "instance_directory",
    "project_identity_for",
]
