from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from tinysoul.action.core.call import ActionCall, ActionExecution, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResultStatus
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeRuntimeCopyRequired,
    AgentHomeRuntimeCopyTrapHandler,
    AgentHomeSettings,
    HomeDomainGuidanceProvider,
    HomeResourceReadExecutor,
    HomeTopLink,
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    HOME_RUNTIME_COPY_REQUIRED,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTransferAction,
    TrapSnap,
)


T = TypeVar("T")


def test_home_provides_default_background_and_domain_guidance(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("core rules", encoding="utf-8")
    how_action = tmp_path / "home" / "how_action" / "workspace"
    how_action.mkdir(parents=True)
    (how_action / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    defaults = _run_copy_trap_after_runtime_exception(
        home.default_background_entries,
        home=home,
    )
    loadable = _run_copy_trap_after_runtime_exception(
        home.loadable_background_entries,
        home=home,
    )
    guidance = _run_copy_trap_after_runtime_exception(
        lambda: HomeDomainGuidanceProvider(home).guidance_for(("workspace",)),
        home=home,
    )

    assert defaults[0].link == "home:agent@core"
    assert defaults[0].content == "core rules"
    assert any(entry.link == "home:how_action@workspace" for entry in loadable)
    assert guidance == ("workspace guidance",)
    assert (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").is_file()
    assert (tmp_path / "runtime" / "home" / "how_action" / "workspace" / "DOMAIN.md").is_file()


def test_home_runtime_copy_can_be_prepared_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill text", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    home.ensure_runtime_copy(HomeTopLink("how", "refactor"))

    assert (tmp_path / "runtime" / "home" / "how" / "refactor" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "skill text"


def test_home_runtime_copy_trap_prepares_copy_and_retries_current_frame(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill text", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn")
        .push(RunLevel.PHASE, "phase3")
    )

    result = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:how@refactor"},
            scope=scope,
        )
    )

    assert result.transfer.action is RuntimeTransferAction.RETRY
    assert result.transfer.target == scope.current()
    assert (tmp_path / "runtime" / "home" / "how" / "refactor" / "SKILL.md").is_file()


def test_home_resource_read_executor_returns_bounded_text(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "how" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    execution = _execution(
        "home.resource.read",
        {"link": "home:how/refactor/references/checklist.md", "max_chars": 3},
    )

    executor = HomeResourceReadExecutor(home)
    with_runtime_copy = _run_copy_trap_after_runtime_exception(
        lambda: executor.execute(execution, ActionExecutionContext()),
        home=home,
    )

    assert with_runtime_copy.status is ActionResultStatus.SUCCESS
    assert with_runtime_copy.payload["text"] == "abc"
    assert with_runtime_copy.payload["truncated"] is True


def test_home_domain_guidance_uses_runtime_copy_trap(tmp_path: Path) -> None:
    how_action = tmp_path / "home" / "how_action" / "workspace"
    how_action.mkdir(parents=True)
    (how_action / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    provider = HomeDomainGuidanceProvider(home)

    guidance = _run_copy_trap_after_runtime_exception(
        lambda: provider.guidance_for(("workspace",)),
        home=home,
    )

    assert guidance == ("workspace guidance",)


def _execution(action_name: str, params: JsonObject) -> ActionExecution:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="home", description="Home."),),
        actions=(
            ActionSpec(
                name=action_name,
                domain="home",
                tool=ActionToolSpec(
                    name=action_name,
                    description="Read.",
                    schema={
                        "type": "object",
                        "properties": {
                            "link": {"type": "string"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["link"],
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


def _run_copy_trap_after_runtime_exception(
    callback: Callable[[], T],
    *,
    home: AgentHomeEngine,
) -> T:
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn")
        .push(RunLevel.PHASE, "phase")
    )
    try:
        return callback()
    except AgentHomeRuntimeCopyRequired as exc:
        _handle_copy_trap(
            home,
            message=str(exc),
            payload={
                "link": exc.link,
                "source_path": str(exc.source_path),
                "runtime_path": str(exc.runtime_path),
            },
            scope=scope,
        )
    except RuntimeException as exc:
        assert exc.reason == HOME_RUNTIME_COPY_REQUIRED
        _handle_copy_trap(
            home,
            message=exc.message,
            payload=exc.payload,
            scope=scope,
        )
    return callback()


def _handle_copy_trap(
    home: AgentHomeEngine,
    *,
    message: str,
    payload: JsonObject,
    scope: RunScope,
) -> None:
    trap_result = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message=message,
            payload=payload,
            scope=scope,
        )
    )
    assert trap_result.transfer.action is RuntimeTransferAction.RETRY
