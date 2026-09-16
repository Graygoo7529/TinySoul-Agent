"""Read-only Web search and page extraction capability."""

from .actions import register_web_actions
from .config import (
    KimiSearchSettings,
    WebDiscoverySettings,
    WebFetchSettings,
    WebSettings,
    parse_web_settings,
)
from .dependencies import web_dependency_requirements

__all__ = [
    "KimiSearchSettings",
    "WebDiscoverySettings",
    "WebFetchSettings",
    "WebSettings",
    "parse_web_settings",
    "register_web_actions",
    "web_dependency_requirements",
]
