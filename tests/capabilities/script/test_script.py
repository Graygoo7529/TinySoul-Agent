from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action import ActionExecutionControl
from tinysoul.capabilities import parse_capabilities_settings
from tinysoul.capabilities.script.config import ScriptSettings
from tinysoul.capabilities.script.errors import ScriptStateError
from tinysoul.capabilities.script.jobs import ScriptJobManager
from tinysoul.capabilities.script.models import ScriptJobState, ScriptLanguage, ScriptSource
from tinysoul.infra import StagingDirectoryManager
from tinysoul.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceMirrorConflict,
    WorkspaceMirrorService,
    WorkspaceSettings,
)


def test_script_settings_parse_language_and_supervision_limits() -> None:
    settings = parse_capabilities_settings(
        {
            "script": {
                "bash": {"enabled": True, "executable": "custom-bash"},
                "max_supervision_cycles": 9,
                "default_wait_seconds": 20,
            }
        }
    ).script

    assert settings.python.enabled is True
    assert settings.bash.enabled is True
    assert settings.bash.executable == "custom-bash"
    assert settings.max_supervision_cycles == 9
    assert settings.default_wait_seconds == 20


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


def test_python_job_requires_explicit_apply(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    record = workspace.write_text(
        "workspace:scripts/create.py",
        "from pathlib import Path\nPath('result.txt').write_text('done', encoding='utf-8')\n",
        owner_turn_id="turn_1",
    )
    manager = _jobs(local_tmp, workspace)

    observation = manager.start(
        turn_id="turn_1",
        source=ScriptSource(
            link=record.link,
            text=workspace.read_text(record.link).text,
            digest=record.digest,
            language=ScriptLanguage.PYTHON,
        ),
        args=(),
        control=ActionExecutionControl(),
        bus=None,
    )

    assert observation.payload["job_state"] == ScriptJobState.READY_TO_APPLY.value
    assert not (workspace.root / "result.txt").exists()
    execution_id = str(observation.payload["execution_id"])
    applied = manager.apply(turn_id="turn_1", execution_id=execution_id)
    assert applied.payload["job_state"] == "applied"
    assert workspace.read_text("workspace:result.txt").text == "done"
    assert manager.has_unresolved("turn_1") is False


def test_failed_and_stopped_jobs_cannot_apply(local_tmp: Path) -> None:
    workspace = _workspace(local_tmp)
    failed_record = workspace.write_text(
        "workspace:scripts/fail.py",
        "raise SystemExit(2)\n",
        owner_turn_id="turn_fail",
    )
    manager = _jobs(local_tmp, workspace)
    failed = manager.start(
        turn_id="turn_fail",
        source=ScriptSource(
            failed_record.link,
            "raise SystemExit(2)\n",
            failed_record.digest,
            ScriptLanguage.PYTHON,
        ),
        args=(),
        control=ActionExecutionControl(),
        bus=None,
    )
    failed_id = str(failed.payload["execution_id"])
    assert failed.failed is True
    with pytest.raises(ScriptStateError):
        manager.apply(turn_id="turn_fail", execution_id=failed_id)
    manager.discard(turn_id="turn_fail", execution_id=failed_id)

    stopped_record = workspace.write_text(
        "workspace:scripts/wait.py",
        "import time\ntime.sleep(30)\n",
        owner_turn_id="turn_stop",
    )
    running = manager.start(
        turn_id="turn_stop",
        source=ScriptSource(
            stopped_record.link,
            "import time\ntime.sleep(30)\n",
            stopped_record.digest,
            ScriptLanguage.PYTHON,
        ),
        args=(),
        control=ActionExecutionControl(),
        bus=None,
    )
    running_id = str(running.payload["execution_id"])
    assert running.payload["job_state"] == ScriptJobState.RUNNING.value
    stopped = manager.stop(turn_id="turn_stop", execution_id=running_id)
    assert stopped.payload["job_state"] == ScriptJobState.STOPPED.value
    with pytest.raises(ScriptStateError):
        manager.apply(turn_id="turn_stop", execution_id=running_id)
    manager.discard(turn_id="turn_stop", execution_id=running_id)


def _settings() -> ScriptSettings:
    return ScriptSettings(
        initial_wait_seconds=1,
        min_wait_seconds=1,
        default_wait_seconds=1,
        max_wait_seconds=2,
        max_runtime_seconds=30,
        max_supervision_cycles=3,
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


def _jobs(root: Path, workspace) -> ScriptJobManager:
    staging = StagingDirectoryManager(root.resolve())
    staging.prepare()
    return ScriptJobManager(
        settings=_settings(),
        mirror_service=_mirrors(workspace),
        staging=staging,
    )
