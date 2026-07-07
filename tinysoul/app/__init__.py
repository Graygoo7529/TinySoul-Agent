"""TinySoul application assembly layer."""

from .builder import TinySoulAppBuilder
from .config import AppSettings, InputCommandSettings, parse_app_settings
from .errors import AppContractError, AppError, AppInvariantError
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
from .runtime import TinySoulApp
from .sources import TerminalInputSource

__all__ = [
    "AppContractError",
    "AppError",
    "AppFailureKind",
    "AppInvariantError",
    "AppSettings",
    "InputCommandParser",
    "InputCommandSettings",
    "InputDispatcher",
    "InputEvent",
    "InputIntent",
    "InputIntentKind",
    "InputSink",
    "InputSource",
    "TerminalInputSource",
    "TinySoulApp",
    "TinySoulAppBuilder",
    "parse_app_settings",
]
