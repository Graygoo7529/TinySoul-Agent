from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from hashlib import sha256
import asyncio
from time import monotonic
from types import SimpleNamespace
from typing import NoReturn, cast

import pytest

from tinysoul.kernel.action import ActionExecutionControl
from tinysoul.plugins.capabilities import parse_capabilities_settings
from tinysoul.plugins.capabilities.script.config import ScriptSettings
from tinysoul.plugins.capabilities.script.errors import ScriptContractError
from tinysoul.plugins.capabilities.script.models import ScriptLanguage, ScriptSource
from tinysoul.plugins.capabilities.script.process import ScriptProcessPreparer
from tinysoul.plugins.capabilities.script.sources import ScriptSourceResolver
from tinysoul.plugins.capabilities.supervised_process import (
    SupervisedProcessManager,
    SupervisedProcessObservation,
    SupervisedProcessOwner,
    SupervisedProcessSettings,
    SupervisedProcessState,
)
from tinysoul.plugins.capabilities.supervised_process.errors import (
    SupervisedProcessContractError,
    SupervisedProcessExecutionError,
    SupervisedProcessStateError,
)
from tinysoul.kernel.context import build_input_append_signal
from tinysoul.plugins.home import AgentHomeEngine, AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.infra import StagingDirectoryManager
from tinysoul.infra.config import ConfigError
from tinysoul.runtime import (
    RunLevel,
    RunScope,
    RuntimeException,
    Signal,
    SignalBus,
)
from tinysoul.plugins.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceMirrorConflict,
    WorkspaceMirrorService,
    WorkspaceSettings,
)
from tests.support.process import PYTHON_WAIT_FOREVER, wait_until, settled_process


def test_script_settings_parse_language_and_supervision_limits() -> None:
    settings = parse_capabilities_settings(
        {
            "script": {
                "bash": {"enabled": True, "executable": "custom-bash"},
            },
            "supervised_process": {
                "max_runtime_seconds": 20,
            },
        }
    )

    assert settings.script.python.enabled is True
    assert settings.script.bash.enabled is True
    assert settings.script.bash.executable == "custom-bash"
    assert settings.supervised_process.max_runtime_seconds == 20


@pytest.mark.parametrize(
    ("values", "key"),
    (
        ({"cycle_wait_seconds": 0}, "cycle_wait_seconds"),
        (
            {"initial_wait_seconds": 11, "max_runtime_seconds": 10},
            "initial_wait_seconds",
        ),
    ),
)
def test_supervised_process_configuration_rejects_inconsistent_limits(
    values: dict[str, int],
    key: str,
) -> None:
    with pytest.raises(ConfigError) as raised:
        parse_capabilities_settings({"supervised_process": values})

    assert raised.value.key == f"capabilities.supervised_process.{key}"


def test_script_rejects_removed_shared_process_settings() -> None:
    with pytest.raises(ConfigError) as raised:
        parse_capabilities_settings(
            {"script": {"default_wait_seconds": 20}}
        )

    assert raised.value.key == "capabilities.script.default_wait_seconds"


def test_workspace_mirror_commits_diff_and_preserves_other_path(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    original = workspace.write_text(
        "workspace:input.txt",
        "before",
        owner_turn_id="turn_0",
    )
    mirror = _mirrors(workspace).create(local_tmp / "mirror")
    assert (
        next(item for item in mirror.entries if item.link == original.link).owner_turn_id
        == "turn_0"
    )
    (mirror.root / "input.txt").write_text("after", encoding="utf-8")
    (mirror.root / "created.txt").write_text("created", encoding="utf-8")
    workspace.write_text(
        "workspace:unrelated.txt",
        "concurrent",
        owner_turn_id="turn_other",
    )

    result = _mirrors(workspace).commit(mirror, owner_turn_id="turn_1")

    assert set(result.links) == {"workspace:created.txt", "workspace:input.txt"}
    assert workspace.read_text("workspace:input.txt").text == "after"
    assert workspace.read_text("workspace:created.txt").text == "created"
    assert workspace.read_text("workspace:unrelated.txt").text == "concurrent"
    record = next(
        item
        for item in workspace.snapshot().resources
        if item.link == "workspace:input.txt"
    )
    assert record.owner_turn_id == original.owner_turn_id
    assert record.digest != original.digest


def test_workspace_mirror_rejects_same_path_conflict(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    original = workspace.write_text(
        "workspace:input.txt",
        "before",
        owner_turn_id="turn_0",
    )
    service = _mirrors(workspace)
    mirror = service.create(local_tmp / "mirror")
    (mirror.root / "input.txt").write_text("job", encoding="utf-8")
    workspace.write_text(
        "workspace:input.txt",
        "concurrent",
        overwrite=True,
        expected_digest=original.digest,
    )

    with pytest.raises(WorkspaceMirrorConflict):
        service.commit(mirror, owner_turn_id="turn_1")

    assert workspace.read_text("workspace:input.txt").text == "concurrent"


async def test_python_job_requires_explicit_apply(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/create.py",
        "from pathlib import Path\nPath('result.txt').write_text('done', encoding='utf-8')\n",
        owner_turn_id="turn_1",
    )
    manager = _jobs(local_tmp, workspace)

    observation = await _start(
        manager,
        turn_id="turn_1",
        source=ScriptSource(
            link=record.link,
            text=workspace.read_text(record.link).text,
            digest=record.digest,
            language=ScriptLanguage.PYTHON,
        ),
    )

    assert observation.payload["job_state"] == SupervisedProcessState.READY_TO_APPLY.value
    assert observation.payload["remaining_runtime_seconds"] == 0.0
    activity = observation.payload["observed_activity"]
    assert isinstance(activity, dict)
    assert activity["activity_since_last_observation"] is True
    assert activity["workspace_diff_changed"] is True
    assert activity["candidate_count_delta"] == 1
    assert not (workspace.root / "result.txt").exists()
    execution_id = str(observation.payload["execution_id"])
    applied = await manager.apply(
        turn_id="turn_1",
        execution_id=execution_id,
    )
    assert applied.payload["job_state"] == "applied"
    assert workspace.read_text("workspace:result.txt").text == "done"
    assert manager.has_unresolved("turn_1") is False


async def test_failed_and_stopped_jobs_cannot_apply(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    failed_record = workspace.write_text(
        "workspace:scripts/fail.py",
        "raise SystemExit(2)\n",
        owner_turn_id="turn_fail",
    )
    manager = _jobs(local_tmp, workspace)
    failed = await _start(
        manager,
        turn_id="turn_fail",
        source=ScriptSource(
            failed_record.link,
            "raise SystemExit(2)\n",
            failed_record.digest,
            ScriptLanguage.PYTHON,
        ),
    )
    failed_id = str(failed.payload["execution_id"])
    assert failed.failed is True
    with pytest.raises(SupervisedProcessStateError):
        await manager.apply(
            turn_id="turn_fail",
            execution_id=failed_id,
        )
    await manager.discard(
        turn_id="turn_fail",
        execution_id=failed_id,
    )

    stopped_record = workspace.write_text(
        "workspace:scripts/wait.py",
        PYTHON_WAIT_FOREVER,
        owner_turn_id="turn_stop",
    )
    running = await _start(
        manager,
        turn_id="turn_stop",
        source=ScriptSource(
            stopped_record.link,
            PYTHON_WAIT_FOREVER,
            stopped_record.digest,
            ScriptLanguage.PYTHON,
        ),
    )
    running_id = str(running.payload["execution_id"])
    assert running.payload["job_state"] == SupervisedProcessState.RUNNING.value
    manager.stop(
        turn_id="turn_stop",
        execution_id=running_id,
    )
    assert manager.registry.get("turn_stop", running_id).poll().state.value == "stopped"
    with pytest.raises(SupervisedProcessStateError):
        await manager.apply(
            turn_id="turn_stop",
            execution_id=running_id,
        )
    await manager.discard(
        turn_id="turn_stop",
        execution_id=running_id,
    )


async def test_job_rejects_workspace_source_changed_after_snapshot(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    original = workspace.write_text(
        "workspace:scripts/task.py",
        "print('old')\n",
        owner_turn_id="turn_1",
    )
    source = ScriptSource(
        original.link,
        "print('old')\n",
        original.digest,
        ScriptLanguage.PYTHON,
    )
    workspace.write_text(
        original.link,
        "print('new')\n",
        overwrite=True,
        expected_digest=original.digest,
    )
    manager = _jobs(local_tmp, workspace)

    with pytest.raises(
        (ScriptContractError, WorkspaceMirrorConflict),
        match="changed .*Script mirror|changed after policy validation",
    ):
        await _start(
            manager,
            turn_id="turn_1",
            source=source,
        )

    assert manager.has_unresolved("turn_1") is False
    assert not tuple(
        (local_tmp / "runtime" / ".staging").glob("supervised-process-job-*")
    )


async def test_promote_writes_the_frozen_source_snapshot(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/task.py",
        "print('checked')\n",
        owner_turn_id="turn_1",
    )
    home = _home(local_tmp)
    resolver = ScriptSourceResolver(
        workspace=WorkspaceService(workspace),
        home=HomeService(home),
        max_source_chars=100,
    )
    source = await resolver.read(record.link)
    workspace.write_text(
        record.link,
        "print('changed')\n",
        overwrite=True,
        expected_digest=record.digest,
    )

    await resolver.promote(
        source,
        "home:skills/test/scripts/task.py",
        expected_source_digest=source.digest,
        overwrite=False,
        expected_target_digest="",
    )

    assert home.read_resource("home:skills/test/scripts/task.py").text == "print('checked')\n"


async def test_source_resolver_enforces_write_and_patch_limits(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    resolver = ScriptSourceResolver(
        workspace=WorkspaceService(workspace),
        home=HomeService(_home(local_tmp)),
        max_source_chars=5,
    )
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        await resolver.write(
            "workspace:scripts/task.py",
            "123456",
            overwrite=False,
            expected_digest="",
            owner_turn_id="turn_1",
        )
    record = workspace.write_text(
        "workspace:scripts/task.py",
        "12345",
        owner_turn_id="turn_1",
    )
    source = await resolver.read(record.link)
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        await resolver.patch(source, old_text="5", new_text="56")

    assert workspace.read_text(record.link).text == "12345"


async def test_source_resolver_checks_target_existence_without_reading_source(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    resolver = ScriptSourceResolver(
        workspace=WorkspaceService(workspace),
        home=HomeService(_home(local_tmp)),
        max_source_chars=5,
    )

    assert await resolver.target_exists("workspace:scripts/task.py") is False
    workspace.write_text(
        "workspace:scripts/task.py",
        "longer than the script read limit",
        owner_turn_id="turn_1",
    )

    assert await resolver.target_exists("workspace:scripts/task.py") is True


async def test_source_resolver_enforces_read_rewrite_and_promote_limits(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    oversized = workspace.write_text(
        "workspace:scripts/oversized.py",
        "123456",
        owner_turn_id="turn_1",
    )
    home = _home(local_tmp)
    resolver = ScriptSourceResolver(
        workspace=WorkspaceService(workspace),
        home=HomeService(home),
        max_source_chars=5,
    )

    with pytest.raises(ScriptContractError, match="exceeds 5"):
        await resolver.read(oversized.link)
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        await resolver.write(
            oversized.link,
            "abcdef",
            overwrite=True,
            expected_digest=oversized.digest,
            owner_turn_id="turn_1",
        )
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        await resolver.promote(
            ScriptSource(
                oversized.link,
                "abcdef",
                oversized.digest,
                ScriptLanguage.PYTHON,
            ),
            "home:skills/test/scripts/task.py",
            expected_source_digest=oversized.digest,
            overwrite=False,
            expected_target_digest="",
        )

    assert not home.resource_exists("home:skills/test/scripts/task.py")


def _settings() -> ScriptSettings:
    return ScriptSettings()


def _process_settings() -> SupervisedProcessSettings:
    return SupervisedProcessSettings(


        max_runtime_seconds=30,
    )


def _workspace(root: Path):
    return WorkspaceEngineBuilder(
        WorkspaceSettings(root=(root / "workspace").resolve(), max_files=100)
    ).build()


def _mirrors(workspace):
    return WorkspaceMirrorService(
        workspace,
        max_files=100,
        max_total_bytes=10_000_000,
        max_file_bytes=1_000_000,
    )


def _jobs(
    root: Path,
    workspace,
    *,
    settings: SupervisedProcessSettings | None = None,
    clock: Callable[[], float] = monotonic,
) -> SupervisedProcessManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return SupervisedProcessManager(
        settings=settings or _process_settings(),

        mirror_service=_mirrors(workspace),
        staging=staging,
        clock=clock,
    )


async def _start(
    manager: SupervisedProcessManager,
    *,
    turn_id: str,
    source: ScriptSource,
):
    observation = await manager.start(
        turn_id=turn_id,
        owner=SupervisedProcessOwner.SCRIPT,
        identity={
            "source_link": source.link,
            "source_digest": source.digest,
            "source_snapshot_digest": source.snapshot_digest,
            "language": source.language.value,
        },
        prepare=ScriptProcessPreparer(
            source=source,
            args=(),
            settings=_settings(),
        ),
        control=ActionExecutionControl(),
    )
    if source.text != PYTHON_WAIT_FOREVER:
        return await settled_process(manager, turn_id, observation)
    return observation


def _turn_scope(turn_id: str) -> RunScope:
    return RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, turn_id)


class _AdvancingClock:
    def __init__(self, *, step: float) -> None:
        self._value = 0.0
        self._step = step

    def __call__(self) -> float:
        self._value += self._step
        return self._value


def _home(root: Path) -> AgentHomeEngine:
    skill = root / "home" / "skills" / "test" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\ntitle: Test\ndescription: Test skill.\n---\nTest.", encoding="utf-8")
    return AgentHomeEngineBuilder(AgentHomeSettings(
        original_root=root / "home", runtime_root=root / "runtime" / "home",
    )).build()
