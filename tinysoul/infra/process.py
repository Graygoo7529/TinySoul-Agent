"""Managed subprocess execution with shared stop/deadline semantics."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import time
from typing import Mapping

from tinysoul.action.framework.run_config import RunConfig, TerminationReason
from tinysoul.trap import ActionCancelledError, ActionExecutionError, ActionTimeoutError


@dataclass
class ManagedProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class ManagedProcessRunner:
    """Run a child process and stop it on RunConfig stop/deadline requests."""

    def run(
        self,
        cmd: list[str],
        *,
        run_config: RunConfig,
        input_bytes: bytes | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        stdout=None,
        stderr=None,
        timeout_label: str | None = None,
    ) -> ManagedProcessResult:
        run_config.raise_if_terminated()
        stdout_target = subprocess.PIPE if stdout is None else stdout
        stderr_target = subprocess.PIPE if stderr is None else stderr

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if input_bytes else None,
                stdout=stdout_target,
                stderr=stderr_target,
                env=dict(env) if env is not None else None,
                cwd=cwd,
            )
        except FileNotFoundError as e:
            raise ActionExecutionError(f"Command not found: {cmd[0]}") from e

        try:
            if input_bytes and proc.stdin is not None:
                proc.stdin.write(input_bytes)
                proc.stdin.close()
                proc.stdin = None

            while proc.poll() is None:
                if run_config.is_termination_requested():
                    self.terminate(proc)
                    if run_config.termination_reason == TerminationReason.TIMEOUT:
                        raise ActionTimeoutError(
                            self._timeout_message(cmd, run_config, timeout_label),
                            action_name=run_config.action_name,
                        )
                    raise ActionCancelledError(
                        f"Command stopped: {' '.join(cmd)}",
                        action_name=run_config.action_name,
                    )

                remaining = run_config.remaining()
                if remaining is not None and remaining <= 0:
                    run_config.request_termination(TerminationReason.TIMEOUT)
                    self.terminate(proc)
                    raise ActionTimeoutError(
                        self._timeout_message(cmd, run_config, timeout_label),
                        action_name=run_config.action_name,
                    )

                sleep_for = 0.05
                if remaining is not None:
                    sleep_for = min(sleep_for, max(remaining, 0.0))
                if sleep_for > 0:
                    time.sleep(sleep_for)

            stdout_bytes, stderr_bytes = proc.communicate()
        except Exception:
            if proc.poll() is None:
                self.terminate(proc)
            raise

        return ManagedProcessResult(
            returncode=proc.returncode,
            stdout=stdout_bytes or b"",
            stderr=stderr_bytes or b"",
        )

    @staticmethod
    def terminate(proc: subprocess.Popen) -> None:
        """Terminate a child process, escalating to kill if it does not exit."""
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)

    @staticmethod
    def _timeout_message(
        cmd: list[str],
        run_config: RunConfig,
        timeout_label: str | None,
    ) -> str:
        budget = timeout_label or (
            f"{run_config.timeout}s" if run_config.timeout is not None else "deadline"
        )
        return f"Command timed out after {budget}: {' '.join(cmd)}"
