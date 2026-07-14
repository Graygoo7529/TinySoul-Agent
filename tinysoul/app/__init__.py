"""TinySoul application assembly layer."""

from .builder import TinySoulAppBuilder
from .config import (
    AppSettings,
    InputCommandSettings,
    OutputSettings,
    SchedulerSettings,
    parse_app_settings,
)
from .errors import AppContractError, AppError, AppInvariantError, AppOutputError
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
from .outputs import ConsoleOutputSink, ObservationRouter, OutputSink
from .maintenance import TerminalHomeDecisionBroker
from .runtime import TinySoulApp
from .sources import MaintenanceSchedule, MaintenanceScheduler, TerminalInputSource

__all__ = [
    "AppContractError",
    "AppError",
    "AppFailureKind",
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
    "OutputSettings",
    "OutputSink",
    "TerminalInputSource",
    "TerminalHomeDecisionBroker",
    "MaintenanceSchedule",
    "MaintenanceScheduler",
    "SchedulerSettings",
    "TinySoulApp",
    "TinySoulAppBuilder",
    "parse_app_settings",
]
