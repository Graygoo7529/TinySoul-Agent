"""Temporary script action execution."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.action.core.specs import ActionBackendSpec

from .subprocess import run_process_action


@dataclass(frozen=True)
class TemporaryScriptOptions:
    """Validated temporary script backend options."""

    language: str = "python"
    code_param: str = "code"
    args_param: str = "args"
    stdin_param: str | None = None
    stdout_limit: int = 12000
    stderr_limit: int = 8000


class TemporaryScriptBackendOptionsValidator:
    """Validate temporary script backend options during catalog loading."""

    def validate(self, backend: ActionBackendSpec, *, key: str) -> None:
        parse_temporary_script_options(backend.options, key=key)


class TemporaryScriptExecutor:
    """Execute a temporary Python script from action parameters."""

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        try:
            options = parse_temporary_script_options(
                execution.action.backend.options,
                key=f"ActionBackendSpec({execution.action.name}).backend.options",
            )
        except ConfigError as exc:
            return _execution_failure(
                execution,
                "Temporary script action backend options are invalid.",
                frame_data={
                    "reason": "invalid_backend_options",
                    "error_type": type(exc).__name__,
                    "key": exc.key,
                },
            )
        code = execution.call.params.get(options.code_param)
        if not isinstance(code, str) or not code:
            return _execution_failure(
                execution,
                "Temporary script action requires non-empty code.",
                frame_data={"reason": "missing_code", "code_param": options.code_param},
            )
        args = _args(execution, options)
        stdin_text = _stdin_text(execution, options)
        with TemporaryDirectory(prefix="tinysoul_action_") as directory:
            script_path = Path(directory) / "action_script.py"
            script_path.write_text(code, encoding="utf-8")
            return run_process_action(
                execution,
                context,
                argv=(sys.executable, str(script_path), *args),
                stdin_text=stdin_text,
                stdout_limit=options.stdout_limit,
                stderr_limit=options.stderr_limit,
            )


def parse_temporary_script_options(options: JsonObject, *, key: str) -> TemporaryScriptOptions:
    """Return validated temporary script options or raise ConfigError."""

    _reject_unknown_options(
        options,
        allowed={
            "language",
            "code_param",
            "args_param",
            "stdin_param",
            "stdout_limit",
            "stderr_limit",
        },
        key=key,
    )
    language = _option_string(options, "language", default="python", key=key)
    if language != "python":
        raise ConfigError(
            "Temporary script language is not supported",
            key=f"{key}.language",
            value=language,
            expected="python",
        )
    return TemporaryScriptOptions(
        language=language,
        code_param=_option_string(options, "code_param", default="code", key=key),
        args_param=_option_string(options, "args_param", default="args", key=key),
        stdin_param=_optional_string(options, "stdin_param", key=key),
        stdout_limit=_positive_int_option(options, "stdout_limit", default=12000, key=key),
        stderr_limit=_positive_int_option(options, "stderr_limit", default=8000, key=key),
    )


def _args(execution: ActionExecution, options: TemporaryScriptOptions) -> tuple[str, ...]:
    value = execution.call.params.get(options.args_param)
    if value is None:
        return ()
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return ()
        result.append(item)
    return tuple(result)


def _stdin_text(execution: ActionExecution, options: TemporaryScriptOptions) -> str | None:
    if options.stdin_param is None:
        return None
    value = execution.call.params.get(options.stdin_param)
    if isinstance(value, str):
        return value
    return None


def _reject_unknown_options(
    options: JsonObject,
    *,
    allowed: set[str],
    key: str,
) -> None:
    unknown = sorted(name for name in options if name not in allowed)
    if unknown:
        raise ConfigError(
            "Unsupported temporary script backend option",
            key=f"{key}.{unknown[0]}",
            value=options[unknown[0]],
            expected=", ".join(sorted(allowed)),
        )


def _option_string(options: JsonObject, name: str, *, default: str, key: str) -> str:
    value = options.get(name)
    if value is None:
        return default
    if isinstance(value, str) and value:
        return value
    raise ConfigError(
        "Temporary script backend option must be a non-empty string",
        key=f"{key}.{name}",
        value=value,
        expected="str",
    )


def _optional_string(options: JsonObject, name: str, *, key: str) -> str | None:
    value = options.get(name)
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    raise ConfigError(
        "Temporary script backend option must be a non-empty string",
        key=f"{key}.{name}",
        value=value,
        expected="str",
    )


def _positive_int_option(options: JsonObject, name: str, *, default: int, key: str) -> int:
    value = options.get(name)
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise ConfigError(
        "Temporary script backend option must be a positive integer",
        key=f"{key}.{name}",
        value=value,
        expected="positive int",
    )


def _execution_failure(
    execution: ActionExecution,
    model_feedback: str,
    *,
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
        frame_data=frame_data,
    )
