from __future__ import annotations

from pathlib import Path
import shutil
import sys

import pytest

from tinysoul.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutionControl,
    ActionFramework,
)
from tinysoul.action.backends import ManagedProcessRequest
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.capabilities import parse_capabilities_settings
from tinysoul.capabilities.shell.config import (
    ShellAdapterSettings,
    ShellSettings,
)
from tinysoul.capabilities.shell.errors import ShellContractError
from tinysoul.capabilities.shell.models import ShellInterpreter
from tinysoul.capabilities.shell.policy import ShellPolicy
from tinysoul.capabilities.shell.process import (
    ShellProcessPreparer,
    resolve_shell_working_directory,
)
from tinysoul.capabilities.supervised_process import (
    SupervisedProcessAnswerGuard,
    SupervisedProcessManager,
    SupervisedProcessOwner,
    SupervisedProcessSettings,
    SupervisedProcessState,
    build_supervised_process_environment,
)
from tinysoul.capabilities.supervised_process.errors import (
    SupervisedProcessStateError,
)
from tinysoul.infra import StagingDirectoryManager
from tinysoul.runtime import RunScope
from tinysoul.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceMirror,
    WorkspaceMirrorService,
    WorkspaceSettings,
)


def test_shell_settings_parse_independent_adapters() -> None:
    settings = parse_capabilities_settings(
        {
            "shell": {
                "enabled": True,
                "max_command_chars": 1234,
                "powershell": {"enabled": True, "executable": "pwsh-test"},
                "cmd": {"enabled": False, "executable": "cmd-test"},
                "bash": {"enabled": True, "executable": "bash-test"},
            }
        }
    ).shell

    assert settings.enabled is True
    assert settings.max_command_chars == 1234
    assert settings.powershell == ShellAdapterSettings(True, "pwsh-test")
    assert settings.cmd == ShellAdapterSettings(False, "cmd-test")
    assert settings.bash == ShellAdapterSettings(True, "bash-test")


def test_shell_policy_and_working_directory_reject_unsafe_structure(
    local_tmp: Path,
) -> None:
    policy = ShellPolicy(max_command_chars=4)
    with pytest.raises(ShellContractError, match="non-empty"):
        policy.validate("  ")
    with pytest.raises(ShellContractError, match="NUL"):
        policy.validate("a\x00b")
    with pytest.raises(ShellContractError, match="exceeds"):
        policy.validate("12345")

    root = local_tmp / "mirror"
    root.mkdir()
    (root / "nested").mkdir()
    assert resolve_shell_working_directory(root, "nested") == root / "nested"
    for value in ("../outside", "/outside", "C:/outside", "nested\\child"):
        with pytest.raises(ShellContractError):
            resolve_shell_working_directory(root, value)


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell unavailable")
def test_powershell_success_without_diff_completes_and_cleans(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)

    observation = _start_shell(
        manager,
        turn_id="turn_1",
        interpreter=ShellInterpreter.POWERSHELL,
        executable=shutil.which("powershell") or "powershell",
        command="Write-Output 'ok'",
    )

    assert observation.payload["job_state"] == SupervisedProcessState.COMPLETED.value
    assert observation.payload["owner"] == "shell"
    assert "command" not in observation.payload
    assert observation.payload["command_digest"]
    assert "ok" in observation.payload["stdout"]["text"]
    assert manager.has_unresolved("turn_1") is False
    assert not tuple(
        (local_tmp / "runtime" / ".staging").glob("supervised-process-job-*")
    )


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell unavailable")
def test_powershell_workspace_diff_requires_apply(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    command = (
        "$p = Join-Path $env:TINYSOUL_WORKSPACE 'result.txt'; "
        "[IO.File]::WriteAllText($p, 'done', [Text.UTF8Encoding]::new($false))"
    )

    observation = _start_shell(
        manager,
        turn_id="turn_1",
        interpreter=ShellInterpreter.POWERSHELL,
        executable=shutil.which("powershell") or "powershell",
        command=command,
    )

    assert observation.payload["job_state"] == "ready_to_apply"
    assert not (workspace.root / "result.txt").exists()
    execution_id = str(observation.payload["execution_id"])
    applied = manager.apply(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )
    assert applied.payload["job_state"] == "applied"
    assert workspace.read_text("workspace:result.txt").text == "done"
    assert manager.has_unresolved("turn_1") is False


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell unavailable")
def test_failed_shell_job_is_retained_and_cannot_apply(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    observation = _start_shell(
        manager,
        turn_id="turn_1",
        interpreter=ShellInterpreter.POWERSHELL,
        executable=shutil.which("powershell") or "powershell",
        command="Write-Error 'bad'; exit 7",
    )
    execution_id = str(observation.payload["execution_id"])

    assert observation.failed is True
    assert observation.payload["job_state"] == "failed"
    assert observation.payload["exit_code"] == 7
    assert manager.has_unresolved("turn_1") is True
    with pytest.raises(SupervisedProcessStateError):
        manager.apply(
            turn_id="turn_1",
            owner=SupervisedProcessOwner.SHELL,
            execution_id=execution_id,
        )
    manager.discard(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )


@pytest.mark.skipif(shutil.which("cmd") is None, reason="Cmd unavailable")
def test_cmd_uses_the_same_supervised_lifecycle(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    observation = _start_shell(
        manager,
        turn_id="turn_1",
        interpreter=ShellInterpreter.CMD,
        executable=shutil.which("cmd") or "cmd",
        command="echo cmd-ok",
    )

    assert observation.payload["job_state"] == "completed"
    assert "cmd-ok" in observation.payload["stdout"]["text"]
    assert manager.has_unresolved("turn_1") is False


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell unavailable")
def test_script_and_shell_share_one_owner_checked_job(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    running = _start_shell(
        manager,
        turn_id="turn_1",
        interpreter=ShellInterpreter.POWERSHELL,
        executable=shutil.which("powershell") or "powershell",
        command="Start-Sleep -Seconds 30",
    )
    execution_id = str(running.payload["execution_id"])

    with pytest.raises(SupervisedProcessStateError, match="another capability"):
        manager.stop(
            turn_id="turn_1",
            owner=SupervisedProcessOwner.SCRIPT,
            execution_id=execution_id,
        )
    with pytest.raises(SupervisedProcessStateError, match="already has"):
        _start_shell(
            manager,
            turn_id="turn_1",
            interpreter=ShellInterpreter.POWERSHELL,
            executable=shutil.which("powershell") or "powershell",
            command="Write-Output 'second'",
        )
    manager.stop(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )
    manager.discard(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )


def test_shared_answer_guard_rejects_shell_owned_unresolved_job(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    running = manager.start(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        identity={"command_digest": "test-digest"},
        prepare=_SleepingProcessPreparer(),
        control=ActionExecutionControl(),
        bus=None,
        auto_complete_without_changes=True,
    )
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    answer = catalog.get_action("core.answer")
    outcome = SupervisedProcessAnswerGuard(manager).check(
        ActionExecution(
            action=answer,
            call=ActionCall(
                call_id="answer_1",
                action_name="core.answer",
                params={"guide_blocks": [{"text": "answer"}]},
                sequence=1,
            ),
            framework=ActionFramework(
                invoke_id="invoke_1",
                batch_id="batch_1",
                scope=RunScope(),
                domain="core",
                turn_id="turn_1",
            ),
        ),
        ActionExecutionContext(),
    )

    assert outcome.ok is False
    assert outcome.frame_data["reason"] == "unresolved_supervised_process_job"
    execution_id = str(running.payload["execution_id"])
    manager.stop(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )
    manager.discard(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )


def _workspace(root: Path):
    return WorkspaceEngineBuilder(
        WorkspaceSettings(root=(root / "workspace").resolve(), max_files=100)
    ).build()


def _manager(root: Path, workspace) -> SupervisedProcessManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return SupervisedProcessManager(
        settings=SupervisedProcessSettings(
            initial_wait_seconds=1,
            cycle_wait_seconds=1,
            min_wait_seconds=1,
            default_wait_seconds=1,
            max_wait_seconds=2,
            max_runtime_seconds=30,
            max_supervision_cycles=3,
        ),
        mirror_service=WorkspaceMirrorService(
            workspace,
            max_files=100,
            max_total_bytes=10_000_000,
            max_file_bytes=1_000_000,
        ),
        staging=staging,
    )


class _SleepingProcessPreparer:
    def __call__(
        self,
        staging_root: Path,
        mirror: WorkspaceMirror,
    ) -> ManagedProcessRequest:
        del staging_root
        return ManagedProcessRequest(
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            cwd=str(mirror.root),
            env=build_supervised_process_environment(mirror.root),
            inherit_env=False,
        )


def _start_shell(
    manager: SupervisedProcessManager,
    *,
    turn_id: str,
    interpreter: ShellInterpreter,
    executable: str,
    command: str,
):
    return manager.start(
        turn_id=turn_id,
        owner=SupervisedProcessOwner.SHELL,
        identity={
            "command_digest": "test-digest",
            "interpreter": interpreter.value,
            "working_directory": ".",
        },
        prepare=ShellProcessPreparer(
            interpreter=interpreter,
            adapter=ShellAdapterSettings(True, executable),
            command=command,
            working_directory=".",
        ),
        control=ActionExecutionControl(),
        bus=None,
        auto_complete_without_changes=True,
    )
