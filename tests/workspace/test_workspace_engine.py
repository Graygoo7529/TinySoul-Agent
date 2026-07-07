from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action.core.call import ActionCall, ActionExecution, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.context import SIGNAL_WORKING_PATCH
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RunLevel, RunScope, SignalBus
from tinysoul.workspace import (
    WorkspaceContractError,
    WorkspaceEngineBuilder,
    WorkspaceLink,
    WorkspaceSettings,
)
from tinysoul.workspace.actions import WorkspaceDescribeExecutor, workspace_scan


def test_workspace_link_rejects_unsafe_paths() -> None:
    assert str(WorkspaceLink.parse("workspace:docs/a.md")) == "workspace:docs/a.md"
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("file:docs/a.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:../secret.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:C:/secret.md")


def test_workspace_scan_updates_manifest_and_emits_working_patch(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored").write_text("x", encoding="utf-8")
    manifest_path = tmp_path / ".tinysoul" / "workspace_manifest.json"
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()
    bus = SignalBus()
    execution = _execution("workspace.scan", {})

    payload = workspace_scan(engine, bus)(execution, ActionExecutionContext(signal_bus=bus))

    assert payload["count"] == 1
    assert payload["resources"] == [
        {"link": "workspace:docs/a.md", "summary": ".md file, 5 bytes"}
    ]
    assert manifest_path.is_file()
    signals = bus.consume_namespace("context")
    assert len(signals) == 1
    assert signals[0].name == SIGNAL_WORKING_PATCH
    patch = signals[0].payload["patch"]
    assert isinstance(patch, dict)
    set_resources = patch["set_resources"]
    assert isinstance(set_resources, list)
    first_resource = set_resources[0]
    assert isinstance(first_resource, dict)
    assert first_resource["link"] == "workspace:docs/a.md"


def test_workspace_scan_manifest_file_does_not_hide_root(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    manifest_path = tmp_path / "workspace_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()

    result = engine.scan()

    assert [resource.link for resource in result.resources] == ["workspace:a.md"]


def test_workspace_read_text_returns_bounded_text(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    result = engine.read_text("workspace:a.md", max_chars=3)

    assert result.link == "workspace:a.md"
    assert result.text == "abc"
    assert result.truncated is True
    assert engine.load_manifest().resources[0].link == "workspace:a.md"


def test_workspace_describe_executor_updates_manifest_and_working_patch(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    bus = SignalBus()
    execution = _execution("workspace.describe", {"link": "workspace:a.md"})

    result = WorkspaceDescribeExecutor(engine, bus).execute(
        execution,
        ActionExecutionContext(signal_bus=bus),
    )

    assert result.status.value == "success"
    assert result.payload["summary"] == ".md file, 5 bytes"
    assert engine.load_manifest().resources[0].link == "workspace:a.md"
    signals = bus.consume_namespace("context")
    assert signals[0].name == SIGNAL_WORKING_PATCH


def _execution(action_name: str, params: JsonObject) -> ActionExecution:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="workspace", description="Workspace."),),
        actions=(
            ActionSpec(
                name=action_name,
                domain="workspace",
                tool=ActionToolSpec(
                    name=action_name,
                    description="Scan.",
                    schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler=action_name,
                ),
            ),
        ),
    )
    preparation = ActionExecutionBuilder().prepare_batch(
        (ActionCall("call_1", action_name, params, 1),),
        catalog=catalog,
        scope=RunScope().push(RunLevel.PHASE, "phase3"),
        batch_id="batch_1",
    )
    return preparation.batch.executions[0]
