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
    SupervisedProcessWaitPolicy,
)
from tinysoul.plugins.capabilities.supervised_process.errors import (
    SupervisedProcessContractError,
    SupervisedProcessExecutionError,
    SupervisedProcessStateError,
)
from tinysoul.kernel.context import build_input_append_signal
from tinysoul.plugins.home import AgentHomeEngine
from tinysoul.infra import StagingDirectoryManager
from tinysoul.infra.config import ConfigError
from tinysoul.runtime import (
    RunLevel,
    RunScope,
    RuntimeException,
    Signal,
    SignalBus,
    SignalWatch,
)
from tinysoul.plugins.capabilities.supervised_process.runtime_bridge import RuntimeSupervisedProcessBridge
from tinysoul.plugins.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceMirrorConflict,
    WorkspaceMirrorService,
    WorkspaceSettings,
)
from tests.support.process import PYTHON_WAIT_FOREVER, wait_until


def test_script_settings_parse_language_and_supervision_limits() -> None:
    settings = parse_capabilities_settings(
        {
            "script": {
                "bash": {"enabled": True, "executable": "custom-bash"},
            },
            "supervised_process": {
                "cycle_wait_seconds": 20,
            },
        }
    )

    assert settings.script.python.enabled is True
    assert settings.script.bash.enabled is True
    assert settings.script.bash.executable == "custom-bash"
    assert settings.supervised_process.cycle_wait_seconds == 20


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
    assert observation.payload["wake_reason"] == "process_exited"
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
    stopped = manager.stop(
        turn_id="turn_stop",
        execution_id=running_id,
    )
    assert stopped.payload["job_state"] == SupervisedProcessState.STOPPED.value
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
            bus=_FailingCloseSignalBus(),
        )

    assert manager.has_unresolved("turn_1") is False
    assert not tuple(
        (local_tmp / "runtime" / ".staging").glob("supervised-process-job-*")
    )


def test_promote_writes_the_frozen_source_snapshot(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/task.py",
        "print('checked')\n",
        owner_turn_id="turn_1",
    )
    home = _RecordingHome()
    resolver = ScriptSourceResolver(
        workspace=workspace,
        home=cast(AgentHomeEngine, home),
        max_source_chars=100,
    )
    source = resolver.read(record.link)
    workspace.write_text(
        record.link,
        "print('changed')\n",
        overwrite=True,
        expected_digest=record.digest,
    )

    resolver.promote(
        source,
        "home:skills/test/scripts/task.py",
        expected_source_digest=source.digest,
        overwrite=False,
        expected_target_digest="",
    )

    assert home.written_text == "print('checked')\n"


def test_source_resolver_enforces_write_and_patch_limits(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    resolver = ScriptSourceResolver(
        workspace=workspace,
        home=cast(AgentHomeEngine, _RecordingHome()),
        max_source_chars=5,
    )
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        resolver.write(
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
    source = resolver.read(record.link)
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        resolver.patch(source, old_text="5", new_text="56")

    assert workspace.read_text(record.link).text == "12345"


def test_source_resolver_checks_target_existence_without_reading_source(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    resolver = ScriptSourceResolver(
        workspace=workspace,
        home=cast(AgentHomeEngine, _RecordingHome()),
        max_source_chars=5,
    )

    assert resolver.target_exists("workspace:scripts/task.py") is False
    workspace.write_text(
        "workspace:scripts/task.py",
        "longer than the script read limit",
        owner_turn_id="turn_1",
    )

    assert resolver.target_exists("workspace:scripts/task.py") is True


def test_source_resolver_enforces_read_rewrite_and_promote_limits(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    oversized = workspace.write_text(
        "workspace:scripts/oversized.py",
        "123456",
        owner_turn_id="turn_1",
    )
    home = _RecordingHome()
    resolver = ScriptSourceResolver(
        workspace=workspace,
        home=cast(AgentHomeEngine, home),
        max_source_chars=5,
    )

    with pytest.raises(ScriptContractError, match="exceeds 5"):
        resolver.read(oversized.link)
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        resolver.write(
            oversized.link,
            "abcdef",
            overwrite=True,
            expected_digest=oversized.digest,
            owner_turn_id="turn_1",
        )
    with pytest.raises(ScriptContractError, match="exceeds 5"):
        resolver.promote(
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

    assert home.written_text == ""


async def test_cycle_pacing_failure_uses_supervised_process_runtime_bridge(
    local_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/wait.py",
        PYTHON_WAIT_FOREVER,
        owner_turn_id="turn_1",
    )
    manager = _jobs(
        local_tmp,
        workspace,
        runtime_bridge=RuntimeSupervisedProcessBridge(),
    )
    running = await _start(
        manager,
        turn_id="turn_1",
        source=ScriptSource(
            record.link,
            workspace.read_text(record.link).text,
            record.digest,
            ScriptLanguage.PYTHON,
        ),
    )

    def fail_refresh(_job: object) -> NoReturn:
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(manager, "_refresh", fail_refresh)
    with pytest.raises(RuntimeException) as raised:
        await manager.wait_before_cycle("turn_1", bus=SignalBus())

    assert raised.value.payload["module"] == "supervised_process"
    assert raised.value.payload["kind"] == "supervised_process.internal_failure"
    assert raised.value.payload["operation"] == "wait_before_cycle"
    monkeypatch.undo()
    manager.stop(
        turn_id="turn_1",
        execution_id=str(running.payload["execution_id"]),
    )
    await manager.discard(
        turn_id="turn_1",
        execution_id=str(running.payload["execution_id"]),
    )


async def test_signal_watch_close_failure_is_aggregated_after_job_cleanup(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/done.py",
        "print('done')\n",
        owner_turn_id="turn_1",
    )
    manager = _jobs(local_tmp, workspace)
    await _start(
        manager,
        turn_id="turn_1",
        source=ScriptSource(
            record.link,
            workspace.read_text(record.link).text,
            record.digest,
            ScriptLanguage.PYTHON,
        ),
        bus=_FailingCloseSignalBus(),
    )
    staging_roots = tuple(
        (local_tmp / "runtime" / ".staging").glob("supervised-process-job-*")
    )

    diagnostics = await manager.cleanup_turn("turn_1")
    assert len(diagnostics) == 1 and diagnostics[0].resource == "job.cleanup"

    assert manager.has_unresolved("turn_1") is False
    assert staging_roots and not staging_roots[0].exists()


async def test_job_wait_ignores_unrelated_signals_and_accepts_current_turn_input(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/wait.py",
        PYTHON_WAIT_FOREVER,
        owner_turn_id="turn_1",
    )
    manager = _jobs(local_tmp, workspace)
    bus = SignalBus()
    running = await _start(
        manager,
        turn_id="turn_1",
        source=ScriptSource(
            record.link,
            workspace.read_text(record.link).text,
            record.digest,
            ScriptLanguage.PYTHON,
        ),
        bus=bus,
    )
    execution_id = str(running.payload["execution_id"])
    waiter = asyncio.create_task(manager.wait(
        turn_id="turn_1", execution_id=execution_id, wait_seconds=15,
        control=ActionExecutionControl(), bus=bus,
    ))
    await asyncio.sleep(0)
    bus.emit(
        Signal(
            name="workspace.sync",
            source="test",
            scope=_turn_scope("turn_1"),
            payload={},
        )
    )
    bus.emit(
        build_input_append_signal(
            "wrong turn",
            scope=_turn_scope("turn_2"),
            source="test",
        )
    )
    await asyncio.sleep(0.05)
    assert not waiter.done()
    bus.emit(
        build_input_append_signal(
            "inspect progress",
            scope=_turn_scope("turn_1"),
            source="test",
        )
    )
    observation = await asyncio.wait_for(waiter, 1.0)
    assert observation.payload["wake_reason"] == "user_input"
    assert observation.payload["requested_wait_seconds"] == 15
    assert cast(float, observation.payload["actual_wait_seconds"]) < 15
    assert cast(float, observation.payload["remaining_runtime_seconds"]) > 0
    manager.stop(
        turn_id="turn_1",
        execution_id=execution_id,
    )
    await manager.discard(
        turn_id="turn_1",
        execution_id=execution_id,
    )


async def test_running_job_paces_automatic_cycles_but_not_after_explicit_wait(
    local_tmp: Path,
) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/wait.py",
        "import threading\nprint('started', flush=True)\nthreading.Event().wait()\n",
        owner_turn_id="turn_1",
    )
    clock = _AdvancingClock(step=5.0)
    manager = _jobs(
        local_tmp,
        workspace,
        settings=SupervisedProcessSettings(
            initial_wait_seconds=1,
            cycle_wait_seconds=15,
            max_runtime_seconds=1_800,
        ),
        clock=clock,
    )
    bus = SignalBus()
    running = await _start(
        manager,
        turn_id="turn_1",
        source=ScriptSource(
            record.link,
            workspace.read_text(record.link).text,
            record.digest,
            ScriptLanguage.PYTHON,
        ),
        bus=bus,
    )
    execution_id = str(running.payload["execution_id"])
    staging_roots = tuple(
        (local_tmp / "runtime" / ".staging").glob("supervised-process-job-*")
    )
    assert len(staging_roots) == 1
    assert (staging_roots[0] / "logs" / "stdout.log").is_file()
    assert (staging_roots[0] / "logs" / "stderr.log").is_file()

    with pytest.raises(SupervisedProcessContractError):
        await manager.wait(
            turn_id="turn_1",
            execution_id=execution_id,
            wait_seconds=14,
            control=ActionExecutionControl(),
            bus=None,
        )

    await manager.wait_before_cycle("turn_1", bus=bus)
    started = monotonic()
    await manager.wait_before_cycle("turn_1", bus=bus)
    assert monotonic() - started >= 0.08

    waited = await manager.wait(
        turn_id="turn_1",
        execution_id=execution_id,
        wait_seconds=15,
        control=ActionExecutionControl(),
        bus=None,
    )
    assert waited.payload["wake_reason"] == "requested_interval_elapsed"
    assert cast(float, waited.payload["actual_wait_seconds"]) >= 15
    started = monotonic()
    await manager.wait_before_cycle("turn_1", bus=bus)
    assert monotonic() - started < 0.08

    manager.stop(
        turn_id="turn_1",
        execution_id=execution_id,
    )
    await manager.discard(
        turn_id="turn_1",
        execution_id=execution_id,
    )
    assert not staging_roots[0].exists()


def _settings() -> ScriptSettings:
    return ScriptSettings()


def _process_settings() -> SupervisedProcessSettings:
    return SupervisedProcessSettings(
        initial_wait_seconds=1,
        cycle_wait_seconds=15,
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
    runtime_bridge: RuntimeSupervisedProcessBridge | None = None,
    settings: SupervisedProcessSettings | None = None,
    clock: Callable[[], float] = monotonic,
) -> SupervisedProcessManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return SupervisedProcessManager(
        settings=settings or _process_settings(),
        wait_policy=SupervisedProcessWaitPolicy(15, 15, 60),
        mirror_service=_mirrors(workspace),
        staging=staging,
        runtime_bridge=runtime_bridge,
        clock=clock,
    )


async def _start(
    manager: SupervisedProcessManager,
    *,
    turn_id: str,
    source: ScriptSource,
    bus: SignalBus | None = None,
):
    return await manager.start(
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
        bus=bus,
    )


def _turn_scope(turn_id: str) -> RunScope:
    return RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, turn_id)


class _AdvancingClock:
    def __init__(self, *, step: float) -> None:
        self._value = 0.0
        self._step = step

    def __call__(self) -> float:
        self._value += self._step
        return self._value


class _RecordingHome:
    written_text = ""

    def loadable_background_links(self) -> tuple[str, ...]:
        return ("home:skills@test",)

    def write_resource(
        self,
        link: str,
        text: str,
        *,
        overwrite: bool,
        expected_digest: str,
    ) -> object:
        del overwrite, expected_digest
        self.written_text = text
        return SimpleNamespace(
            link=link,
            digest=sha256(text.encode("utf-8")).hexdigest(),
            size=len(text.encode("utf-8")),
            state=SimpleNamespace(value="modified"),
        )


class _FailingCloseSignalBus(SignalBus):
    def watch(self) -> SignalWatch:
        return cast(SignalWatch, _FailingCloseSignalWatch())


class _FailingCloseSignalWatch:
    def wait_for_matching(self, _predicate: object, _timeout: float | None) -> None:
        return None

    def close(self) -> NoReturn:
        raise RuntimeError("watch close failed")
