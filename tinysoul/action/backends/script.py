"""Temporary script action execution."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from tinysoul.infra.json import JsonObject

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResult, ActionResultStage

from .subprocess import run_process_action


class TemporaryScriptExecutor:
    """Execute a temporary Python script from action parameters."""

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        options = execution.action.backend.options
        language = _option_string(options, "language", default="python")
        if language != "python":
            return _execution_failure(
                execution,
                f"Temporary script language is not supported: {language}",
                frame_data={"reason": "unsupported_language", "language": language},
            )
        code_param = _option_string(options, "code_param", default="code")
        code = execution.call.params.get(code_param)
        if not isinstance(code, str) or not code:
            return _execution_failure(
                execution,
                "Temporary script action requires non-empty code.",
                frame_data={"reason": "missing_code", "code_param": code_param},
            )
        args = _args(execution, options)
        stdin_text = _stdin_text(execution, options)
        stdout_limit = _positive_int_option(options, "stdout_limit", default=12000)
        stderr_limit = _positive_int_option(options, "stderr_limit", default=8000)
        with TemporaryDirectory(prefix="tinysoul_action_") as directory:
            script_path = Path(directory) / "action_script.py"
            script_path.write_text(code, encoding="utf-8")
            return run_process_action(
                execution,
                context,
                argv=(sys.executable, str(script_path), *args),
                stdin_text=stdin_text,
                stdout_limit=stdout_limit,
                stderr_limit=stderr_limit,
            )


def _args(execution: ActionExecution, options: JsonObject) -> tuple[str, ...]:
    args_param = _option_string(options, "args_param", default="args")
    value = execution.call.params.get(args_param)
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


def _stdin_text(execution: ActionExecution, options: JsonObject) -> str | None:
    stdin_param = options.get("stdin_param")
    if not isinstance(stdin_param, str) or not stdin_param:
        return None
    value = execution.call.params.get(stdin_param)
    if isinstance(value, str):
        return value
    return None


def _option_string(options: JsonObject, name: str, *, default: str) -> str:
    value = options.get(name)
    if isinstance(value, str) and value:
        return value
    return default


def _positive_int_option(options: JsonObject, name: str, *, default: int) -> int:
    value = options.get(name)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


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
