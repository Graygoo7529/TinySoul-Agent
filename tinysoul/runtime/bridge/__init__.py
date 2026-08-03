"""Runtime bridge helpers for module-to-runtime semantic mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .action import RuntimeActionBridge
    from .app import RuntimeAppBridge
    from .context import RuntimeContextBridge
    from .endpoint import RuntimeEndpointBridge
    from .home import RuntimeAgentHomeBridge
    from .infra import RuntimeInfraBridge
    from .llm import RuntimeLLMBridge
    from .loop import RuntimeLoopBridge
    from .maintenance import RuntimeMaintenanceBridge
    from .memory import RuntimeMemoryBridge
    from .session import RuntimeSessionBridge
    from .script import RuntimeScriptBridge
    from .shell import RuntimeShellBridge
    from .supervised_process import RuntimeSupervisedProcessBridge
    from .workspace import RuntimeWorkspaceBridge

__all__ = [
    "RuntimeActionBridge",
    "RuntimeAgentHomeBridge",
    "RuntimeAppBridge",
    "RuntimeContextBridge",
    "RuntimeEndpointBridge",
    "RuntimeInfraBridge",
    "RuntimeLLMBridge",
    "RuntimeLoopBridge",
    "RuntimeMaintenanceBridge",
    "RuntimeMemoryBridge",
    "RuntimeSessionBridge",
    "RuntimeScriptBridge",
    "RuntimeShellBridge",
    "RuntimeSupervisedProcessBridge",
    "RuntimeWorkspaceBridge",
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
    if name == "RuntimeEndpointBridge":
        from .endpoint import RuntimeEndpointBridge

        return RuntimeEndpointBridge
    if name == "RuntimeAgentHomeBridge":
        from .home import RuntimeAgentHomeBridge

        return RuntimeAgentHomeBridge
    if name == "RuntimeInfraBridge":
        from .infra import RuntimeInfraBridge

        return RuntimeInfraBridge
    if name == "RuntimeLLMBridge":
        from .llm import RuntimeLLMBridge

        return RuntimeLLMBridge
    if name == "RuntimeLoopBridge":
        from .loop import RuntimeLoopBridge

        return RuntimeLoopBridge
    if name == "RuntimeMaintenanceBridge":
        from .maintenance import RuntimeMaintenanceBridge

        return RuntimeMaintenanceBridge
    if name == "RuntimeMemoryBridge":
        from .memory import RuntimeMemoryBridge

        return RuntimeMemoryBridge
    if name == "RuntimeSessionBridge":
        from .session import RuntimeSessionBridge

        return RuntimeSessionBridge
    if name == "RuntimeScriptBridge":
        from .script import RuntimeScriptBridge

        return RuntimeScriptBridge
    if name == "RuntimeShellBridge":
        from .shell import RuntimeShellBridge

        return RuntimeShellBridge
    if name == "RuntimeSupervisedProcessBridge":
        from .supervised_process import RuntimeSupervisedProcessBridge

        return RuntimeSupervisedProcessBridge
    if name == "RuntimeWorkspaceBridge":
        from .workspace import RuntimeWorkspaceBridge

        return RuntimeWorkspaceBridge
    raise AttributeError(name)
