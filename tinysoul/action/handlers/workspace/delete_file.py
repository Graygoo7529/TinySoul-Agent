"""
Delete File Action - deletes a file from disk and workspace.
"""
import json

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import RunConfig
from tinysoul.context.protocols import ContextProvider
from tinysoul.context.workspace import ChangeLogItem, ChangeOperation
from tinysoul.trap import ActionInputError

ACTION_SPEC_DELETE_FILE = {
    "name": "delete_file",
    "description": "Delete a file from disk and workspace",
    "cluster": {
        "type": "NATIVE",
        "domain": "WORKSPACE",
    },
    "profile": {
        "action_intention": "EXECUTION",
        "action_environment_effect": "DESTRUCTIVE",
        "action_mode": "SINGLE_RUN",
        "llm_dependency": "NONE",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "need to remove a file from workspace",
            ],
        },
        "preconditions": [
            "target_access must point to an existing file in workspace",
            "file must be within workspace_location boundary",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Removes the corresponding ResourceItem from workspace.resources",
            ],
            "physical_environment_effects": [
                "Deletes the file from disk",
            ],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "target_access": {
                    "type": "string",
                    "description": "Relative path of the file to delete",
                },
            },
            "required": [
                "target_access",
            ],
        },
        "examples": [
            {
                "target_access": "temp_250415_content.md",
            },
        ],
        "edge_case_handling": [
            "File not found: remove ResourceItem anyway and return success",
            "Path traversal outside workspace: reject with error",
        ],
    },
}

ACTION_JSON_DELETE_FILE = json.dumps(ACTION_SPEC_DELETE_FILE, ensure_ascii=False, indent=2)


class DeleteFileExecutor(ActionExecutor):
    """Executor for deleting a file from disk and workspace."""

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        run_config.raise_if_terminated()
        workspace = context_provider.workspace if context_provider else None
        if workspace is None:
            raise RuntimeError("delete_file requires workspace in context")

        target_access = action_input.get("target_access", "")
        if not target_access:
            raise ActionInputError(
                "target_access is required", action_input=action_input
            )

        target_path = workspace.resolve_access(target_access)
        file_existed = target_path.exists()
        if file_existed:
            target_path.unlink()

        # Record deletion in workspace-level audit log before removing the resource.
        workspace.change_log.append(
            ChangeLogItem(
                turn=getattr(context_provider, "current_turn", 0),
                operation=ChangeOperation.DELETED,
                summary=f"Deleted file '{target_access}'",
            )
        )

        workspace.remove_resource(target_access)
        run_config.raise_if_terminated()
        return {
            "message": f"Deleted file '{target_access}'",
            "file_existed": file_existed,
        }


class DeleteFileAction(ActionBase):
    """Action to delete a file from disk and workspace."""

    action_name = "delete_file"
    ACTION_JSON = ACTION_JSON_DELETE_FILE
    _executor = DeleteFileExecutor()


def register_to(registry):
    """Register delete_file action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(DeleteFileAction)
