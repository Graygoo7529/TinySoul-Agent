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
    AppInvariantError,
    AppOutputError,
)
from .initializer import ProjectInitializationOutcome, ProjectInitializer
from .failures import AppFailureKind
from .inputs import (
    InputCommandParser,
    InputDispatcher,
    InputEvent,
    InputIntent,
    InputIntentKind,
    InputSink,
    InputSource,
)
from .outputs import ConsoleOutputSink, ObservationRoute, ObservationRouter, OutputSink
from .maintenance import HomeDecisionBroker, MaintenanceDecisionSnapshot
from .runtime import TinySoulApp
from .sources import MaintenanceSchedule, MaintenanceScheduler, TerminalInputSource

__all__ = [
    "AppContractError",
    "AppError",
    "AppFailureKind",
    "AppInitializationError",
    "AppInvariantError",
    "AppOutputError",
    "AppSettings",
    "ConsoleOutputSink",
    "InputCommandParser",
    "InputCommandSettings",
    "InputDispatcher",
    "InputEvent",
    "InputIntent",
    "InputIntentKind",
    "InputSink",
    "InputSource",
    "ObservationRouter",
    "ObservationRoute",
    "OutputSettings",
    "OutputSink",
    "ProjectInitializationOutcome",
    "ProjectInitializer",
    "TerminalInputSource",
    "HomeDecisionBroker",
    "MaintenanceDecisionSnapshot",
    "MaintenanceSchedule",
    "MaintenanceScheduler",
    "SchedulerSettings",
    "TinySoulApp",
    "TinySoulAppBuilder",
    "parse_app_settings",
]
