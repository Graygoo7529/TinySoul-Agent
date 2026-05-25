"""
Base ScriptExecutor for sandboxed Python script execution.

Provides shared logic for script-based executors (loading source,
building execution context) while leaving the actual execution strategy
to subclasses.
"""

from abc import ABC
from pathlib import Path
from typing import Any

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.infra.config import settings
from tinysoul.context.protocols import ContextProvider


class ScriptExecutor(ActionExecutor, ABC):
    """
    Base for executors that run Python scripts in a controlled environment.

    Subclasses may differ in:
    - How the script is located (workspace temp dir vs system scripts dir)
    - Whether AST validation is performed (temporary scripts need it,
      persistent scripts may skip if pre-audited)
    - Whether the compiled AST is cached
    """

    def __init__(self, script_path: str, timeout: float | None = None):
        self._script_path = script_path
        self._timeout = timeout

    def _load_source(self) -> str:
        """Read script source from disk."""
        return Path(self._script_path).read_text(encoding="utf-8")

    def _build_context(
        self, action_input: dict, context_provider: ContextProvider | None
    ) -> dict[str, Any]:
        """Build the execution context dict passed to the script."""
        ctx: dict[str, Any] = {
            "action_input": action_input,
        }
        if context_provider is not None:
            ctx["query_events"] = context_provider.query_events
            ctx["loop_target"] = context_provider.loop_target
            ctx["current_turn"] = context_provider.current_turn
            workspace = getattr(context_provider, "workspace", None)
            if workspace is not None:
                ws_loc = getattr(workspace, "workspace_location", None)
                if ws_loc is not None:
                    ctx["workspace_location"] = str(ws_loc)
        return ctx
