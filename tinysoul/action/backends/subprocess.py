"""Subprocess-backed action execution."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping

from tinysoul.infra.json import JsonObject, dumps_json

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResult, ActionResultStage


class SubprocessActionExecutor:
    """Execute an action by launching a configured subprocess."""

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        options = execution.action.backend.options
        argv = _string_list_option(options, "argv")
        if not argv:
            return _execution_failure(
                execution,
                "Subprocess action has no argv configured.",
                frame_data={"reason": "missing_argv"},
            )
        cwd = _optional_string(options, "cwd")
        env = _string_mapping_option(options, "env")
        stdin_text = _stdin_text(execution, options)
        stdout_limit = _positive_int_option(options, "stdout_limit", default=8000)
        stderr_limit = _positive_int_option(options, "stderr_limit", default=4000)
        return run_process_action(
            execution,
            context,
            argv=argv,
            cwd=cwd,
            env=env,
            stdin_text=stdin_text,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
        )


def run_process_action(
    execution: ActionExecution,
    context: ActionExecutionContext,
    *,
    argv: tuple[str, ...],
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    stdin_text: str | None = None,
    stdout_limit: int = 8000,
    stderr_limit: int = 4000,
) -> ActionResult:
    """Run a subprocess and map its completion into an action result."""

    if context.control.is_cancelled() or context.control.is_expired():
        return _timeout_result(
            execution,
            "Action timed out before subprocess started.",
            frame_data={"reason": "deadline_expired"},
        )
    process_env = None
    if env is not None:
        process_env = {**os.environ, **env}
    try:
        process: subprocess.Popen[str]
        if os.name == "nt":
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=process_env,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=process_env,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                start_new_session=True,
            )
    except OSError as exc:
        return _execution_failure(
            execution,
            f"Subprocess action failed to start: {exc}",
            frame_data={"reason": "process_start_failed", "error_type": type(exc).__name__},
        )

    try:
        stdout, stderr = process.communicate(
            input=stdin_text,
            timeout=context.control.remaining_seconds(),
        )
    except subprocess.TimeoutExpired:
        context.control.request_cancel("timeout")
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        stdout = stdout or ""
        stderr = stderr or ""
        return _timeout_result(
            execution,
            "Subprocess action timed out.",
            payload=_process_payload(process.returncode, stdout, stderr, stdout_limit, stderr_limit),
            frame_data={"reason": "process_timeout", "executor_leaked": False},
        )

    stdout = stdout or ""
    stderr = stderr or ""
    payload = _process_payload(process.returncode, stdout, stderr, stdout_limit, stderr_limit)
    if process.returncode == 0:
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=payload,
        )
    return _execution_failure(
        execution,
        f"Subprocess action exited with code {process.returncode}.",
        payload=payload,
        frame_data={"reason": "process_exit_nonzero"},
    )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, 9)
    except OSError:
        process.kill()


def _stdin_text(execution: ActionExecution, options: JsonObject) -> str | None:
    mode = _optional_string(options, "stdin") or "json_params"
    if mode == "none":
        return None
    if mode == "json_params":
        return dumps_json(execution.call.params)
    return mode


def _process_payload(
    return_code: int | None,
    stdout: str,
    stderr: str,
    stdout_limit: int,
    stderr_limit: int,
) -> JsonObject:
    stdout_value, stdout_truncated = _truncate(stdout, stdout_limit)
    stderr_value, stderr_truncated = _truncate(stderr, stderr_limit)
    return {
        "exit_code": return_code,
        "stdout": stdout_value,
        "stderr": stderr_value,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _string_list_option(options: JsonObject, name: str) -> tuple[str, ...]:
    value = options.get(name)
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return ()
        result.append(item)
    return tuple(result)


def _string_mapping_option(options: JsonObject, name: str) -> dict[str, str] | None:
    value = options.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            return None
        result[key] = item
    return result


def _optional_string(options: JsonObject, name: str) -> str | None:
    value = options.get(name)
    if isinstance(value, str) and value:
        return value
    return None


def _positive_int_option(options: JsonObject, name: str, *, default: int) -> int:
    value = options.get(name)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _execution_failure(
    execution: ActionExecution,
    model_feedback: str,
    *,
    payload: JsonObject | None = None,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        payload=payload,
        frame_data=frame_data,
    )


def _timeout_result(
    execution: ActionExecution,
    model_feedback: str,
    *,
    payload: JsonObject | None = None,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.timeout(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        payload=payload,
        frame_data=frame_data,
    )
