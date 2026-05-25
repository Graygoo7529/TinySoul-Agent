"""
CLIExecutor for predefined command-line tools.

The command template is fixed at construction time (e.g. ["git"], ["npm"]).
At execution time, action_input is mapped to command-line arguments by the
concrete subclass.

Context is passed via environment variables so that standard CLI tools do
not need to know about stdin JSON protocols.
"""

from tinysoul.action.framework.run_config import RunConfig

from .base import SubprocessExecutor


class CLIExecutor(SubprocessExecutor):
    """
    Executor for running a predefined CLI tool.

    Subclasses must override ``_build_cmd(action_input)`` to map parameters
    to command-line arguments.
    """

    def __init__(self, base_cmd: list[str], timeout: float | None = None):
        super().__init__(timeout)
        self._base_cmd = base_cmd

    def _build_env(self, context_provider) -> dict[str, str]:
        """Build environment variables for the subprocess."""
        env: dict[str, str] = {}
        if context_provider is not None:
            env["TINYSOUL_QUERY_EVENTS"] = str(context_provider.query_events)
            env["TINYSOUL_LOOP_TARGET"] = str(context_provider.loop_target)
            env["TINYSOUL_CURRENT_TURN"] = str(context_provider.current_turn)
        return env

    def _build_cmd(self, action_input: dict) -> list[str]:
        """Override to map action_input to command-line arguments."""
        return self._base_cmd.copy()

    def execute(
        self,
        action_input: dict,
        context_provider,
        run_config: RunConfig,
    ) -> dict:
        run_config.raise_if_terminated()
        cmd = self._build_cmd(action_input)
        env = self._build_env(context_provider)
        return self._run(cmd, run_config=run_config, env=env)
