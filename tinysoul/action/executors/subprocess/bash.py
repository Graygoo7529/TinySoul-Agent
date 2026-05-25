"""
BashExecutor for running arbitrary bash scripts.

Reads the script from action_input["script"] and executes it via
``bash -c``.  Action input and context are passed through stdin as JSON,
so the script can read them with ``cat`` or ``read``.

Includes a basic safety blacklist for obviously dangerous patterns.
"""

import re

from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionInputError
from tinysoul.action.framework.run_config import RunConfig

from .base import SubprocessExecutor


class BashExecutor(SubprocessExecutor):
    """
    Executor that runs an arbitrary bash script string.

    Security note: This is inherently dangerous (arbitrary code execution
    at the OS level).  Consider keeping Bash actions off the default
    allowlist, or requiring explicit user confirmation before execution.
    """

    # Basic patterns that are almost never what an LLM agent should run.
    # This is a coarse guard, not a replacement for sandboxing.
    _DISALLOWED_PATTERNS: list[str] = [
        r"curl\s+.*\|\s*(bash|sh)",
        r"wget\s+.*\|\s*(bash|sh)",
        r"rm\s+-rf\s+/\s*$",
        r"rm\s+-rf\s+/\s+",
        r"mkfs",
        r"dd\s+if=.*of=/dev/sd",
        r">\s*/dev/sda",
        r":\(\)\{\s*:\|:\&\s*\};:",  # fork bomb
    ]

    def __init__(self, timeout: float | None = None):
        super().__init__(timeout)

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        run_config.raise_if_terminated()
        script = action_input.get("script", "")
        if not script:
            raise ActionInputError("'script' is required", action_input=action_input)

        self._validate_script(script)

        input_data = {
            "action_input": action_input,
            "context": self._build_context_dict(context_provider),
        }
        return self._run(["bash", "-c", script], run_config=run_config, input_data=input_data)

    def _validate_script(self, script: str) -> None:
        for pattern in self._DISALLOWED_PATTERNS:
            if re.search(pattern, script, re.IGNORECASE):
                raise ActionInputError(
                    f"Disallowed pattern in bash script: {pattern}",
                    action_input={"script": script},
                )

    def _build_context_dict(self, context_provider: ContextProvider | None) -> dict:
        if context_provider is None:
            return {}
        return {
            "query_events": getattr(context_provider, "query_events", ""),
            "loop_target": getattr(context_provider, "loop_target", ""),
            "current_turn": getattr(context_provider, "current_turn", 0),
        }
