"""TinySoul application assembly layer."""

from .builder import TinySoulAppBuilder
from .config import AppSettings, InputCommandSettings, OutputSettings, parse_app_settings
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
from .runtime import TinySoulApp
from .sources import TerminalInputSource

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
    "TinySoulApp",
    "TinySoulAppBuilder",
    "parse_app_settings",
]
