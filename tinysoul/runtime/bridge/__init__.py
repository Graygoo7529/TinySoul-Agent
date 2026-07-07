"""Runtime bridge helpers for module-to-runtime semantic mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .action import RuntimeActionBridge
    from .app import RuntimeAppBridge
    from .context import RuntimeContextBridge
    from .infra import RuntimeInfraBridge
    from .llm import RuntimeLLMBridge
    from .loop import RuntimeLoopBridge

__all__ = [
    "RuntimeActionBridge",
    "RuntimeAppBridge",
    "RuntimeContextBridge",
    "RuntimeInfraBridge",
    "RuntimeLLMBridge",
    "RuntimeLoopBridge",
]


def __getattr__(name: str) -> object:
    if name == "RuntimeActionBridge":
        from .action import RuntimeActionBridge

        return RuntimeActionBridge
    if name == "RuntimeAppBridge":
        from .app import RuntimeAppBridge

        return RuntimeAppBridge
    if name == "RuntimeContextBridge":
        from .context import RuntimeContextBridge

        return RuntimeContextBridge
    if name == "RuntimeInfraBridge":
        from .infra import RuntimeInfraBridge

        return RuntimeInfraBridge
    if name == "RuntimeLLMBridge":
        from .llm import RuntimeLLMBridge

        return RuntimeLLMBridge
    if name == "RuntimeLoopBridge":
        from .loop import RuntimeLoopBridge

        return RuntimeLoopBridge
    raise AttributeError(name)
