"""
Scan Workspace Action - detects and synchronizes workspace resources with disk.
"""
import json

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.context.protocols import ContextProvider
from tinysoul.trap import ActionExecutionError

ACTION_SPEC_SCAN_WORKSPACE = {
    "name": "scan_workspace",
    "description": "Detect and synchronize workspace resources with disk",
    "cluster": {
        "type": "NATIVE",
        "domain": "WORKSPACE",
    },
    "profile": {
        "action_intention": "EXTERNAL_PROBING",
        "action_environment_effect": "READ_ONLY",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "NONE",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "workspace.resources is empty",
                "workspace may be inconsistent with disk",
            ],
        },
        "preconditions": [
            "workspace_location must be a valid absolute path",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Preserves resource_desc and change_log for resources whose resource_access still exists on disk",
                "Removes stale resources whose resource_access no longer exists on disk",
                "Adds new resources for newly discovered files on disk",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "examples": [
            {},
        ],
        "edge_case_handling": [],
    },
}

ACTION_JSON_SCAN_WORKSPACE = json.dumps(ACTION_SPEC_SCAN_WORKSPACE, ensure_ascii=False, indent=2)


class ScanWorkspaceExecutor(ActionExecutor):
    """Executor for scanning and synchronizing workspace resources."""

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        run_config.raise_if_terminated()
        workspace = context_provider.workspace if context_provider else None
        if workspace is None:
            raise ActionExecutionError("scan_workspace requires workspace in context")

        workspace.scan()
        return {
            "message": f"Scanned workspace at {workspace.workspace_location}",
            "resource_count": len(workspace.resources),
        }


class ScanWorkspaceAction(ActionBase):
    """Action to scan and synchronize workspace resources."""

    action_name = "scan_workspace"
    ACTION_JSON = ACTION_JSON_SCAN_WORKSPACE
    _executor = ScanWorkspaceExecutor()


def register_to(registry):
    """Register scanworkspace action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(ScanWorkspaceAction)
