"""
Git Action - a unified CLI-type action for common git read-only commands.

Instead of one action per git subcommand (git_status, git_log, git_diff...),
this exposes a single ``git`` action where the LLM selects the subcommand
and optional arguments via step-2 parameter generation.

Supported subcommands: status, log, diff, branch, show, remote.
"""
import json

from tinysoul.action.executors.subprocess.cli import CLIExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import ActionRuntimeConfig
from tinysoul.infra.capabilities import ActionDependency
from tinysoul.infra.config import settings
from tinysoul.trap import ActionInputError

ACTION_SPEC_GIT = {
    "name": "git",
    "description": "Execute common read-only git commands in a repository",
    "cluster": {
        "type": "CLI",
        "domain": "GIT",
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
                "need to inspect a git repository",
                "need to check status, history, diffs, or branches",
            ],
        },
        "preconditions": [
            "path must point to a directory inside a git repository",
            "git must be installed and available on PATH",
        ],
        "postconditions": {
            "logical_state_effects": [
                "Returns the git command output as text",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": [
                        "status",
                        "log",
                        "diff",
                        "branch",
                        "show",
                        "remote",
                    ],
                    "description": "Git subcommand to execute",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository (default: current directory)",
                },
                "args": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "Additional arguments for the git subcommand (e.g. ['--oneline', '-n', '5'])",
                },
            },
            "required": [
                "subcommand",
            ],
        },
        "examples": [
            {
                "subcommand": "status",
                "path": ".",
                "args": [
                    "--short",
                ],
            },
            {
                "subcommand": "log",
                "path": ".",
                "args": [
                    "--oneline",
                    "-n",
                    "10",
                ],
            },
            {
                "subcommand": "diff",
                "path": ".",
                "args": [
                    "--stat",
                ],
            },
        ],
        "edge_case_handling": [
            "Path is not a git repository: return error",
            "git is not installed: return error",
            "Unsupported subcommand: return error",
        ],
    },
}

ACTION_JSON_GIT = json.dumps(ACTION_SPEC_GIT, ensure_ascii=False, indent=2)


class GitExecutor(CLIExecutor):
    """Executor for unified git action."""

    ALLOWED_SUBCOMMANDS = {"status", "log", "diff", "branch", "show", "remote"}

    def __init__(self):
        super().__init__(base_cmd=["git"], timeout=None)

    def _build_cmd(self, action_input: dict) -> list[str]:
        subcommand = action_input.get("subcommand", "")
        if not subcommand:
            raise ActionInputError("'subcommand' is required", action_input=action_input)
        if subcommand not in self.ALLOWED_SUBCOMMANDS:
            raise ActionInputError(
                f"Git subcommand '{subcommand}' is not supported. "
                f"Allowed: {', '.join(sorted(self.ALLOWED_SUBCOMMANDS))}",
                action_input=action_input,
            )

        path = action_input.get("path", ".")
        args = action_input.get("args", [])

        # Safety: args are passed as a list to subprocess.run(), which means
        # they are passed directly to git without shell interpretation.
        # This prevents shell injection even if the LLM generates malicious args.
        cmd = ["git", "-C", path, subcommand]
        cmd.extend(args)
        return cmd


class GitAction(ActionBase):
    """Unified git action for read-only git commands."""

    action_name = "git"
    ACTION_JSON = ACTION_JSON_GIT
    _executor = GitExecutor()
    _runtime_config = ActionRuntimeConfig(
        timeout=60.0,
        dependencies=[
            ActionDependency(type="executable", name="git"),
        ],
    )


def register_to(registry):
    """Register git action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(GitAction)
