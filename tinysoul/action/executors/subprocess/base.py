"""
Base SubprocessExecutor for running external commands.

Provides shared logic for subprocess-based executors:
- stdout/stderr capture
- exit-code handling
- timeout control
- JSON round-trip for structured input/output
"""

import json
import os
from abc import ABC
from typing import Any

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.infra.config import settings
from tinysoul.infra.process import ManagedProcessRunner
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError


class SubprocessExecutor(ActionExecutor, ABC):
    """
    Base for executors that run external commands via subprocess.

    Contract with child processes:
    - Input (optional): JSON dict written to stdin.
    - Output: stdout parsed as JSON dict if valid JSON object; otherwise
      if valid JSON but not an object, wrapped as ``{"result": parsed}``;
      if not valid JSON, wrapped as ``{"output": stdout_text}``.
    - Error: non-zero exit code raises ActionExecutionError(stderr).
    """

    def __init__(self, timeout: float | None = None):
        self._timeout = timeout
        self._runner = ManagedProcessRunner()

    def _run(
        self,
        cmd: list[str],
        run_config: RunConfig,
        input_data: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> dict:
        """
        Run a subprocess command with unified error handling.

        Args:
            cmd: Command and arguments as a list.
            input_data: Optional dict to serialize as JSON and feed to stdin.
            env: Extra environment variables (merged over os.environ).
            cwd: Working directory for the subprocess.

        Returns:
            Parsed result dict.

        Raises:
            ActionExecutionError: On timeout, command not found, or non-zero exit.
        """
        full_env = {**os.environ, **(env or {})}

        timeout = self._timeout
        if run_config is not None and run_config.timeout is not None:
            timeout = run_config.timeout
        if timeout is None:
            timeout = settings.action_timeout
        if run_config.deadline is None and timeout is not None:
            run_config.apply_timeout(timeout)

        input_bytes = json.dumps(input_data).encode("utf-8") if input_data else None
        proc_result = self._runner.run(
            cmd,
            run_config=run_config,
            input_bytes=input_bytes,
            env=full_env,
            cwd=cwd,
            timeout_label=f"{timeout}s" if timeout is not None else None,
        )

        if proc_result.returncode != 0:
            stderr = proc_result.stderr.decode("utf-8", errors="replace").strip()
            raise ActionExecutionError(
                f"Command failed (exit {proc_result.returncode}): {stderr}"
            )

        stdout = proc_result.stdout.decode("utf-8", errors="replace").strip()
        if not stdout:
            return {"output": ""}

        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        except json.JSONDecodeError:
            return {"output": stdout}
