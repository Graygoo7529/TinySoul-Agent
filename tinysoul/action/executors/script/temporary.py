"""
Executor for temporary (dynamically registered) script actions.

Reads Python script from a workspace file and executes it in a sandboxed
environment.  The script file is resolved at execution time via the
workspace's resolve_access() so that LLM can reference it by relative path.

After execution, automatically scans the workspace for new/modified files
so that the agent can perceive filesystem changes made by the script.
"""

import json
from typing import Any

from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.infra.sandbox import execute_script
from tinysoul.infra.config import settings
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.context.workspace import ChangeLogItem, ChangeOperation

from .base import ScriptExecutor


class TemporaryScriptExecutor(ScriptExecutor):
    """
    Executor that loads a Python script from a workspace file and runs it
    inside a restricted environment.

    The *script_path* is stored relative to the workspace root.  At execute
    time it is resolved via ``context_provider.workspace.resolve_access()``.
    """

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider,
        run_config: RunConfig,
    ) -> dict:
        if context_provider is None:
            raise ActionExecutionError(
                "TemporaryScriptExecutor requires a ContextProvider"
            )
        run_config.raise_if_terminated()

        workspace = context_provider.workspace
        if workspace is None:
            raise ActionExecutionError(
                "TemporaryScriptExecutor requires workspace in context"
            )

        # 1. Resolve and read script file
        script_file = workspace.resolve_access(self._script_path)
        if not script_file.exists():
            raise ActionExecutionError(f"Script file not found: {self._script_path}")

        source = script_file.read_text(encoding="utf-8")

        # 2. Build context dict for the script
        ctx = self._build_context(action_input, context_provider)

        # 3. Snapshot existing files before execution
        before_files = {r.resource_access for r in workspace.resources}

        # 4. Execute in sandbox
        timeout = self._timeout
        if run_config is not None and run_config.timeout is not None:
            timeout = run_config.timeout
        if timeout is None:
            timeout = settings.script_timeout

        try:
            raw_result = execute_script(
                source,
                action_input,
                ctx,
                timeout=timeout,
                script_path=str(script_file),
                run_config=run_config,
            )
        except (ActionInputError, ActionExecutionError):
            raise
        except Exception as e:
            raise ActionExecutionError(
                f"Script execution failed: {e}", action_input=action_input
            ) from e
        run_config.raise_if_terminated()

        # 5. Scan workspace to detect new/modified files
        workspace.scan()

        # 6. Add change_log entries for newly discovered files
        after_files = {r.resource_access for r in workspace.resources}
        new_files = after_files - before_files
        turn = context_provider.current_turn if context_provider else 0
        for access in new_files:
            resource = workspace.find_resource(access)
            if resource is not None:
                resource.change_log.append(
                    ChangeLogItem(
                        turn=turn,
                        operation=ChangeOperation.CREATED,
                        summary=f"Created by temporary script",
                    )
                )

        # 7. Assemble result
        # execute_script returns {"return_value": ..., "stdout": ...}
        return_value = raw_result.get("return_value") if isinstance(raw_result, dict) else raw_result
        stdout_output = raw_result.get("stdout", "") if isinstance(raw_result, dict) else ""

        result_payload: dict[str, Any] = {}
        if isinstance(return_value, dict):
            result_payload = dict(return_value)
        else:
            try:
                result_payload = {"output": json.loads(json.dumps(return_value, ensure_ascii=False))}
            except (TypeError, ValueError):
                result_payload = {"output": str(return_value)}

        if stdout_output:
            result_payload["stdout"] = stdout_output

        if new_files:
            result_payload["workspace_changes"] = {
                "new_files": sorted(new_files),
            }

        return result_payload
