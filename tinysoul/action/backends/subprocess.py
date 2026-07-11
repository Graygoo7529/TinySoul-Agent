"""Subprocess-backed action execution."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, dumps_json

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.specs import ActionBackendSpec
from tinysoul.action.core.result import ActionResult, ActionResultStage


class SubprocessStdinMode(StrEnum):
    """Supported subprocess stdin modes."""

    JSON_PARAMS = "json_params"
    NONE = "none"


@dataclass(frozen=True)
class SubprocessOptions:
    """Validated subprocess backend options."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: dict[str, str] | None = None
    stdin_mode: SubprocessStdinMode = SubprocessStdinMode.JSON_PARAMS
    stdout_limit: int = 8000
    stderr_limit: int = 4000


class SubprocessBackendOptionsValidator:
    """Validate subprocess backend options during catalog loading."""

    def validate(self, backend: ActionBackendSpec, *, key: str) -> None:
        parse_subprocess_options(backend.options, key=key)


class SubprocessActionExecutor:
    """Execute an action by launching a configured subprocess."""

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        try:
            options = parse_subprocess_options(
                execution.action.backend.options,
                key=f"ActionBackendSpec({execution.action.name}).backend.options",
            )
        except ConfigError as exc:
            return _execution_failure(
                execution,
                "Subprocess action backend options are invalid.",
                frame_data={
                    "reason": "invalid_backend_options",
                    "error_type": type(exc).__name__,
                    "key": exc.key,
                },
            )
        stdin_text = _stdin_text(execution, options)
        return run_process_action(
            execution,
            context,
            argv=options.argv,
            cwd=options.cwd,
            env=options.env,
            stdin_text=stdin_text,
            stdout_limit=options.stdout_limit,
            stderr_limit=options.stderr_limit,
        )


def parse_subprocess_options(options: JsonObject, *, key: str) -> SubprocessOptions:
    """Return validated subprocess options or raise ConfigError."""

    _reject_unknown_options(
        options,
        allowed={"argv", "cwd", "env", "stdin_mode", "stdout_limit", "stderr_limit"},
        key=key,
    )
    return SubprocessOptions(
        argv=_required_string_list(options, "argv", key=key),
        cwd=_optional_string(options, "cwd", key=key),
        env=_optional_string_mapping(options, "env", key=key),
        stdin_mode=_stdin_mode(options, key=key),
        stdout_limit=_positive_int_option(options, "stdout_limit", default=8000, key=key),
        stderr_limit=_positive_int_option(options, "stderr_limit", default=4000, key=key),
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

    def terminate_on_cancel(_reason: str) -> None:
        _terminate_process_tree(process)

    context.control.add_cancel_callback(terminate_on_cancel)
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
    finally:
        context.control.remove_cancel_callback(terminate_on_cancel)

    stdout = stdout or ""
    stderr = stderr or ""
    payload = _process_payload(process.returncode, stdout, stderr, stdout_limit, stderr_limit)
    if context.control.is_cancelled():
        return _timeout_result(
            execution,
            "Subprocess action stopped after cancellation was requested.",
            payload=payload,
            frame_data={
                "reason": context.control.cancel_reason or "cancelled",
                "executor_leaked": False,
            },
        )
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


def _stdin_text(execution: ActionExecution, options: SubprocessOptions) -> str | None:
    if options.stdin_mode is SubprocessStdinMode.NONE:
        return None
    return dumps_json(execution.call.params)


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


def _reject_unknown_options(
    options: JsonObject,
    *,
    allowed: set[str],
    key: str,
) -> None:
    unknown = sorted(name for name in options if name not in allowed)
    if unknown:
        raise ConfigError(
            "Unsupported subprocess backend option",
            key=f"{key}.{unknown[0]}",
            value=options[unknown[0]],
            expected=", ".join(sorted(allowed)),
        )


def _required_string_list(options: JsonObject, name: str, *, key: str) -> tuple[str, ...]:
    value = options.get(name)
    if not isinstance(value, list):
        raise ConfigError(
            "Subprocess backend option must be a non-empty list of strings",
            key=f"{key}.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                "Subprocess backend option must be a non-empty list of strings",
                key=f"{key}.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    if not result:
        raise ConfigError(
            "Subprocess backend option must contain at least one argv item",
            key=f"{key}.{name}",
            value=value,
            expected="non-empty list[str]",
        )
    return tuple(result)


def _optional_string_mapping(
    options: JsonObject,
    name: str,
    *,
    key: str,
) -> dict[str, str] | None:
    value = options.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(
            "Subprocess backend option must be a string mapping",
            key=f"{key}.{name}",
            value=value,
            expected="dict[str, str]",
        )
    result: dict[str, str] = {}
    for item_key, item in value.items():
        if not isinstance(item_key, str) or not item_key or not isinstance(item, str):
            raise ConfigError(
                "Subprocess backend option must be a string mapping",
                key=f"{key}.{name}",
                value=value,
                expected="dict[str, str]",
            )
        result[item_key] = item
    return result


def _optional_string(options: JsonObject, name: str, *, key: str) -> str | None:
    value = options.get(name)
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    raise ConfigError(
        "Subprocess backend option must be a non-empty string",
        key=f"{key}.{name}",
        value=value,
        expected="str",
    )


def _stdin_mode(options: JsonObject, *, key: str) -> SubprocessStdinMode:
    value = options.get("stdin_mode", SubprocessStdinMode.JSON_PARAMS.value)
    if not isinstance(value, str):
        raise ConfigError(
            "Subprocess backend stdin_mode must be a string",
            key=f"{key}.stdin_mode",
            value=value,
            expected="json_params | none",
        )
    try:
        return SubprocessStdinMode(value)
    except ValueError as exc:
        raise ConfigError(
            "Subprocess backend stdin_mode must be supported",
            key=f"{key}.stdin_mode",
            value=value,
            expected="json_params | none",
        ) from exc


def _positive_int_option(options: JsonObject, name: str, *, default: int, key: str) -> int:
    value = options.get(name)
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise ConfigError(
        "Subprocess backend option must be a positive integer",
        key=f"{key}.{name}",
        value=value,
        expected="positive int",
    )


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
