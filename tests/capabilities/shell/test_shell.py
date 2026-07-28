from __future__ import annotations

from base64 import b64decode
from pathlib import Path
import shutil
import sys
import tomllib

import pytest

from tinysoul.app import ProjectConfigProfile, ProjectInitializer
from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutionControl,
    ActionFramework,
    ActionResultStatus,
    builtin_action_catalog_root,
)
from tinysoul.action.backends import ManagedProcessRequest
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.capabilities import parse_capabilities_settings
from tinysoul.capabilities.shell import register_shell_actions
from tinysoul.capabilities.shell.config import (
    ShellAdapterSettings,
    ShellSettings,
)
from tinysoul.capabilities.shell.dependencies import shell_dependency_requirements
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
    SupervisedProcessObservation,
    SupervisedProcessOwner,
    SupervisedProcessSettings,
    SupervisedProcessState,
    build_supervised_process_environment,
)
from tinysoul.capabilities.supervised_process.errors import (
    SupervisedProcessStateError,
)
from tinysoul.context import ContextEngineBuilder
from tinysoul.context.trace import TraceKind
from tinysoul.home import (
    AgentHomeContractError,
    AgentHomeEngineBuilder,
    AgentHomeSettings,
)
from tinysoul.infra import JsonObject, StagingDirectoryManager
from tinysoul.infra.config import ConfigError
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.loop import Phase3Unit
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, SignalBus
from tinysoul.workspace import (
    WorkspaceEngine,
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
    assert tuple(
        requirement.id for requirement in shell_dependency_requirements(settings)
    ) == ("shell.powershell", "shell.bash")


def test_shell_settings_reject_unknown_keys_and_project_profiles_are_explicit(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError) as raised:
        parse_capabilities_settings({"shell": {"unknown": True}})
    assert raised.value.key == "capabilities.shell.unknown"

    standard_root = tmp_path / "standard"
    development_root = tmp_path / "development"
    ProjectInitializer().initialize(standard_root)
    ProjectInitializer().initialize(
        development_root,
        config_profile=ProjectConfigProfile.DEVELOPMENT,
    )
    standard = tomllib.loads(
        (standard_root / "configs" / "capabilities.shell.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["shell"]
    development = tomllib.loads(
        (development_root / "configs" / "capabilities.shell.toml").read_text(
            encoding="utf-8"
        )
    )["capabilities"]["shell"]

    assert development["enabled"] is True
    assert development["powershell"]["enabled"] is True
    assert development["cmd"]["enabled"] is True
    assert development["bash"]["enabled"] is False
    assert standard["enabled"] is False
    assert all(
        standard[name]["enabled"] is False
        for name in ("powershell", "cmd", "bash")
    )


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


def test_shell_working_directory_rejects_symbolic_link(local_tmp: Path) -> None:
    root = local_tmp / "mirror"
    target = root / "target"
    link = root / "linked"
    target.mkdir(parents=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(ShellContractError, match="symbolic links"):
        resolve_shell_working_directory(root, "linked")


def test_shell_preparers_use_fixed_argv_minimal_env_and_no_stdin(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    mirror = WorkspaceMirrorService(
        workspace,
        max_files=100,
        max_total_bytes=10_000_000,
        max_file_bytes=1_000_000,
    ).create(local_tmp / "transaction")
    command = "Write-Output 'fixed'"
    adapters = {
        ShellInterpreter.POWERSHELL: ShellAdapterSettings(True, "pwsh-test"),
        ShellInterpreter.CMD: ShellAdapterSettings(True, "cmd-test"),
        ShellInterpreter.BASH: ShellAdapterSettings(True, "bash-test"),
    }

    requests = {
        interpreter: ShellProcessPreparer(
            interpreter=interpreter,
            adapter=adapter,
            command=command,
            working_directory=".",
        )(local_tmp / "staging", mirror)
        for interpreter, adapter in adapters.items()
    }

    powershell = requests[ShellInterpreter.POWERSHELL]
    assert powershell.argv[:5] == (
        "pwsh-test",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
    )
    assert b64decode(powershell.argv[5]).decode("utf-16-le") == command
    assert requests[ShellInterpreter.CMD].argv == (
        "cmd-test",
        "/D",
        "/Q",
        "/S",
        "/C",
        command,
    )
    assert requests[ShellInterpreter.BASH].argv == (
        "bash-test",
        "--noprofile",
        "--norc",
        "-c",
        command,
    )
    for request in requests.values():
        assert request.cwd == str(mirror.root)
        assert request.inherit_env is False
        assert request.stdin_text is None
        assert request.env is not None
        assert request.env["TINYSOUL_WORKSPACE"] == str(mirror.root)


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
    assert "ok" in _log_text(observation.payload, "stdout")
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
    assert "cmd-ok" in _log_text(observation.payload, "stdout")
    assert manager.has_unresolved("turn_1") is False


@pytest.mark.skipif(shutil.which("bash") is None, reason="Bash unavailable")
def test_bash_opt_in_uses_the_same_supervised_lifecycle(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    observation = _start_shell(
        manager,
        turn_id="turn_1",
        interpreter=ShellInterpreter.BASH,
        executable=shutil.which("bash") or "bash",
        command="printf 'bash-ok\\n'",
    )

    assert observation.payload["job_state"] == "completed"
    assert "bash-ok" in _log_text(observation.payload, "stdout")
    assert manager.has_unresolved("turn_1") is False


def test_shell_timeout_and_stop_remain_owned_until_discard(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    timeout_manager = _manager(
        local_tmp / "timeout",
        workspace,
        settings=SupervisedProcessSettings(
            initial_wait_seconds=1,
            cycle_wait_seconds=15,
            min_wait_seconds=15,
            default_wait_seconds=15,
            max_wait_seconds=60,
            max_runtime_seconds=1,
            max_supervision_cycles=3,
        ),
    )
    timed_out = timeout_manager.start(
        turn_id="turn_timeout",
        owner=SupervisedProcessOwner.SHELL,
        identity={"command_digest": "timeout"},
        prepare=_PythonProcessPreparer("import time; time.sleep(30)"),
        control=ActionExecutionControl(),
        bus=None,
        auto_complete_without_changes=True,
    )
    timeout_id = str(timed_out.payload["execution_id"])

    assert timed_out.timed_out is True
    assert timed_out.payload["job_state"] == "timed_out"
    assert timeout_manager.has_unresolved("turn_timeout") is True
    with pytest.raises(SupervisedProcessStateError):
        timeout_manager.apply(
            turn_id="turn_timeout",
            owner=SupervisedProcessOwner.SHELL,
            execution_id=timeout_id,
        )
    timeout_manager.discard(
        turn_id="turn_timeout",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=timeout_id,
    )

    stop_manager = _manager(local_tmp / "stop", workspace)
    running = stop_manager.start(
        turn_id="turn_stop",
        owner=SupervisedProcessOwner.SHELL,
        identity={"command_digest": "stop"},
        prepare=_PythonProcessPreparer("import time; time.sleep(30)"),
        control=ActionExecutionControl(),
        bus=None,
        auto_complete_without_changes=True,
    )
    stop_id = str(running.payload["execution_id"])
    stopped = stop_manager.stop(
        turn_id="turn_stop",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=stop_id,
    )

    assert stopped.payload["job_state"] == "stopped"
    assert stop_manager.has_unresolved("turn_stop") is True
    stop_manager.discard(
        turn_id="turn_stop",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=stop_id,
    )
    assert stop_manager.has_unresolved("turn_stop") is False


def test_failed_shell_candidate_can_be_read_then_discarded(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    manager = _manager(local_tmp, workspace)
    failed = manager.start(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        identity={"command_digest": "candidate"},
        prepare=_PythonProcessPreparer(
            "import os\n"
            "from pathlib import Path\n"
            "Path(os.environ['TINYSOUL_WORKSPACE'], 'candidate.txt').write_text("
            "'candidate body', encoding='utf-8')\n"
            "raise SystemExit(9)\n"
        ),
        control=ActionExecutionControl(),
        bus=None,
        auto_complete_without_changes=True,
    )
    execution_id = str(failed.payload["execution_id"])

    assert failed.failed is True
    assert failed.payload["candidate_count"] == 1
    candidate = manager.read_candidate(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
        path="candidate.txt",
        cursor=0,
        max_chars=100,
    )
    assert candidate["text"] == "candidate body"
    manager.discard(
        turn_id="turn_1",
        owner=SupervisedProcessOwner.SHELL,
        execution_id=execution_id,
    )
    assert not (workspace.root / "candidate.txt").exists()


def test_shell_effective_catalog_pruning_drives_home_mounts(local_tmp: Path) -> None:
    enabled = ShellSettings(
        enabled=True,
        powershell=ShellAdapterSettings(True, sys.executable),
        cmd=ShellAdapterSettings(False, "cmd"),
        bash=ShellAdapterSettings(False, "bash"),
    )
    process_settings = SupervisedProcessSettings(
        initial_wait_seconds=1,
        cycle_wait_seconds=15,
        min_wait_seconds=20,
        default_wait_seconds=30,
        max_wait_seconds=45,
        max_runtime_seconds=60,
    )
    engine, _, _, _ = _shell_engine(
        local_tmp / "enabled",
        enabled,
        process_settings,
    )
    identifiers = engine.action_identifiers()

    assert engine.domain_names() == ("shell",)
    assert ("shell", "shell.run_powershell") in identifiers
    assert ("shell", "shell.run_cmd") not in identifiers
    assert ("shell", "shell.run_bash") not in identifiers
    scope = engine.phase2_scope(("shell",))
    assert scope.tool_scope is not None
    wait_tool = next(
        tool for tool in scope.tool_scope.visible_tools() if tool.name == "shell.wait"
    )
    properties = wait_tool.parameters["properties"]
    assert isinstance(properties, dict)
    wait_seconds = properties["wait_seconds"]
    assert isinstance(wait_seconds, dict)
    assert wait_seconds["minimum"] == 20
    assert wait_seconds["default"] == 30
    assert wait_seconds["maximum"] == 45

    home_root = local_tmp / "enabled" / "home" / "how_domain" / "shell"
    home_root.mkdir(parents=True)
    (home_root / "DOMAIN.md").write_text("shell guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=local_tmp / "enabled" / "home",
            runtime_root=local_tmp / "enabled" / "runtime" / "home",
        )
    ).build()
    home.reconcile_prompt_mounts(
        domains=engine.domain_names(),
        actions=engine.action_identifiers(),
    )
    assert home.ensure_runtime_copy(
        home.parse_link("home:how_domain:shell")
    ) is True
    assert home.guidance_for_domain("shell") == "shell guidance"

    disabled_engine, _, _, _ = _shell_engine(
        local_tmp / "disabled",
        ShellSettings(enabled=False),
    )
    assert "shell" not in disabled_engine.domain_names()
    (local_tmp / "disabled" / "home").mkdir(parents=True)
    disabled_home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=local_tmp / "disabled" / "home",
            runtime_root=local_tmp / "disabled" / "runtime" / "home",
        )
    ).build()
    disabled_home.reconcile_prompt_mounts(
        domains=disabled_engine.domain_names(),
        actions=disabled_engine.action_identifiers(),
    )
    with pytest.raises(AgentHomeContractError, match="not defined"):
        disabled_home.guidance_for_domain("shell")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell unavailable")
def test_shell_action_engine_result_enters_turn_trace(local_tmp: Path) -> None:
    settings = ShellSettings(
        enabled=True,
        powershell=ShellAdapterSettings(
            True,
            shutil.which("powershell") or "powershell",
        ),
        cmd=ShellAdapterSettings(False, "cmd"),
        bash=ShellAdapterSettings(False, "bash"),
    )
    engine, manager, _, bus = _shell_engine(local_tmp, settings)
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("run an immediate command")
    normalization = engine.normalize(
        (
            ToolCallRecord(
                id="shell_1",
                name="shell.run_powershell",
                arguments={"command": "Write-Output 'trace-ok'"},
                kind=ToolKind.ACTION,
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )

    outcome = Phase3Unit(context=context, action=engine, bus=bus).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.results[0].status is ActionResultStatus.SUCCESS
    assert outcome.results[0].payload["job_state"] == "completed"
    assert "trace-ok" in _log_text(outcome.results[0].payload, "stdout")
    assert context.trace_kinds() == (TraceKind.ACTION_RESULT,)
    assert manager.has_unresolved(turn_id) is False


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
        prepare=_PythonProcessPreparer("import time; time.sleep(30)"),
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

    assert outcome.failure is not None
    assert outcome.failure.reason == "unresolved_supervised_process_job"
    assert outcome.failure.scope == "supervised_process.answer_guard"
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


def _workspace(root: Path) -> WorkspaceEngine:
    return WorkspaceEngineBuilder(
        WorkspaceSettings(root=(root / "workspace").resolve(), max_files=100)
    ).build()


def _manager(
    root: Path,
    workspace: WorkspaceEngine,
    *,
    settings: SupervisedProcessSettings | None = None,
) -> SupervisedProcessManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return SupervisedProcessManager(
        settings=settings
        or SupervisedProcessSettings(
            initial_wait_seconds=1,
            cycle_wait_seconds=15,
            min_wait_seconds=15,
            default_wait_seconds=15,
            max_wait_seconds=60,
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


class _PythonProcessPreparer:
    def __init__(self, source: str) -> None:
        self._source = source

    def __call__(
        self,
        staging_root: Path,
        mirror: WorkspaceMirror,
    ) -> ManagedProcessRequest:
        del staging_root
        return ManagedProcessRequest(
            argv=(sys.executable, "-c", self._source),
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
) -> SupervisedProcessObservation:
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


def _shell_engine(
    root: Path,
    settings: ShellSettings,
    process_settings: SupervisedProcessSettings | None = None,
) -> tuple[ActionEngine, SupervisedProcessManager, WorkspaceEngine, SignalBus]:
    workspace = _workspace(root)
    manager = _manager(root, workspace, settings=process_settings)
    bus = SignalBus()
    with builtin_action_catalog_root() as catalog_root:
        catalog = ActionCatalogLoader().load(catalog_root)
        disabled = tuple(
            action.name for action in catalog.actions() if action.domain != "shell"
        )
        builder = ActionEngineBuilder(catalog_root).disable_actions(*disabled)
        register_shell_actions(
            builder,
            settings=settings,
            jobs=manager,
            bus=bus,
        )
        engine = builder.build()
    return engine, manager, workspace, bus


def _log_text(payload: JsonObject, stream: str) -> str:
    projection = payload.get(stream)
    assert isinstance(projection, dict)
    text = projection.get("text")
    assert isinstance(text, str)
    return text
