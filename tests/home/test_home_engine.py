from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pytest

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
    AgentHomeContractError,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeFailureKind,
    AgentHomeIOError,
    AgentHomeRuntimeCopyRequired,
    AgentHomeRuntimeCopyTrapHandler,
    AgentHomeSettings,
    HomeActionHowProvider,
    HomeBackgroundContentLoader,
    HomeBackgroundEntryProvider,
    HomeDomainHowProvider,
    HomeResourceReadExecutor,
    HomeTopLink,
)
from tinysoul.context import ContextEngineBuilder
from tinysoul.context.background import BackgroundPatch
from tinysoul.context.signals import build_background_patch_signal
from tinysoul.loop.context_signals import ContextSignalConsumer
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    HOME_RUNTIME_COPY_REQUIRED,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeModuleRunner,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
    RuntimeTransferAction,
    TrapSnap,
)


T = TypeVar("T")


def test_home_settings_reject_overlapping_original_and_runtime_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match="must not overlap"):
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "home" / "runtime",
        )


def test_home_background_is_copied_only_when_context_loads_it(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "what" / "project.md"
    source.parent.mkdir(parents=True)
    source.write_text("project knowledge", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    link = "home:what@project"
    context = (
        ContextEngineBuilder(system_text="sys")
        .add_lazy_background(
            link,
            HomeBackgroundContentLoader(home=home, link=link),
        )
        .build()
    )
    turn_id = context.begin_turn("load project background")
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, "phase1")
    )
    bus = SignalBus()
    registry = TrapHandlerRegistry()
    registry.register(
        HOME_RUNTIME_COPY_REQUIRED,
        AgentHomeRuntimeCopyTrapHandler(home),
    )
    consumer = ContextSignalConsumer(
        context=context,
        bus=bus,
        module_runner=RuntimeModuleRunner(
            trap=RuntimeTrap(registry=registry),
            bus=bus,
        ),
    )
    runtime_path = tmp_path / "runtime" / "home" / "what" / "project.md"
    assert not runtime_path.exists()
    bus.emit(
        build_background_patch_signal(
            BackgroundPatch(load_links=(link,)),
            call_id="load_project",
            scope=scope,
            source="test",
        )
    )

    assert consumer.consume(scope=scope) == ()

    assert runtime_path.read_text(encoding="utf-8") == "project knowledge"
    assert context.background_links() == (link,)


def test_home_provides_default_background_without_exposing_domain_how(tmp_path: Path) -> None:
    agent = tmp_path / "home" / "agent"
    agent.mkdir(parents=True)
    (agent / "AGENT.md").write_text("core rules", encoding="utf-8")
    how_domain = tmp_path / "home" / "how_domain" / "workspace"
    how_domain.mkdir(parents=True)
    (how_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    defaults = _run_copy_trap_after_runtime_exception(
        home.default_background_entries,
        home=home,
    )
    loadable = home.loadable_background_links()
    guidance = _run_copy_trap_after_runtime_exception(
        lambda: HomeDomainHowProvider(home).guidance_for(("workspace",)),
        home=home,
    )

    assert defaults[0].link == "home:agent@core"
    assert defaults[0].content == "core rules"
    assert "home:how_domain:workspace" not in loadable
    assert guidance == ("workspace guidance",)
    assert (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").is_file()
    assert (tmp_path / "runtime" / "home" / "how_domain" / "workspace" / "DOMAIN.md").is_file()


def test_home_runtime_copy_can_be_prepared_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill text", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    home.ensure_runtime_copy(HomeTopLink("how", "refactor"))

    assert (tmp_path / "runtime" / "home" / "how" / "refactor" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "skill text"


def test_home_background_provider_catalog_does_not_materialize_core(
    tmp_path: Path,
) -> None:
    agent = tmp_path / "home" / "agent"
    agent.mkdir(parents=True)
    (agent / "AGENT.md").write_text("core rules", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    provider = HomeBackgroundEntryProvider(home)

    catalog = provider.catalog()

    assert catalog.default_links == ("home:agent@core",)
    assert not (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").exists()

    content = _run_copy_trap_after_runtime_exception(
        lambda: provider.load("home:agent@core"),
        home=home,
    )

    assert content == "core rules"
    assert (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").is_file()


def test_home_runtime_copy_trap_prepares_copy_and_retries_current_frame(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "refactor"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill text", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
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

    repeated = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy still required",
            payload={"link": "home:how@refactor"},
            scope=scope,
        )
    )
    assert repeated.transfer.action is RuntimeTransferAction.END
    assert repeated.transfer.target == scope.nearest(RunLevel.TURN)


def test_home_runtime_copy_restores_missing_unmodified_copy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "agent" / "AGENT.md"
    source.parent.mkdir(parents=True)
    source.write_text("rules", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    link = HomeTopLink("agent", "core")
    home.ensure_runtime_copy(link)
    runtime = tmp_path / "runtime" / "home" / "agent" / "AGENT.md"
    runtime.unlink()
    scope = RunScope().push(RunLevel.PROGRAM, "program").push(RunLevel.TURN, "turn")

    result = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": str(link)},
            scope=scope,
        )
    )

    assert result.transfer.action is RuntimeTransferAction.RETRY
    assert result.transfer.target == scope.current()
    assert runtime.read_text(encoding="utf-8") == "rules"


def test_home_resource_read_executor_returns_bounded_text(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "how" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
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

def test_home_resource_read_rejects_automatic_how_spaces(tmp_path: Path) -> None:
    how_domain = tmp_path / "home" / "how_domain" / "workspace"
    how_action = tmp_path / "home" / "how_action" / "workspace"
    how_domain.mkdir(parents=True)
    how_action.mkdir(parents=True)
    (how_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    (how_action / "rewrite.md").write_text("rewrite guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    for link in (
        "home:how_domain:workspace",
        "home:how_action:workspace/rewrite",
        "home:how_domain/workspace/DOMAIN.md",
        "home:how_action/workspace/rewrite.md",
    ):
        result = HomeResourceReadExecutor(home).execute(
            _execution("home.resource.read", {"link": link}),
            ActionExecutionContext(),
        )

        assert result.status is ActionResultStatus.FAILED
        assert result.frame_data["error_type"] == "AgentHomeContractError"


def test_home_resource_read_rejects_non_positive_limit(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "how" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    result = HomeResourceReadExecutor(home).execute(
        _execution(
            "home.resource.read",
            {"link": "home:how/refactor/references/checklist.md", "max_chars": 0},
        ),
        ActionExecutionContext(),
    )

    assert result.status is ActionResultStatus.FAILED
    assert result.frame_data["reason"] == "invalid_max_chars"


def test_home_engine_resource_read_rejects_bool_limit(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "how" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    with pytest.raises(AgentHomeContractError, match="positive"):
        home.read_resource("home:how/refactor/references/checklist.md", max_chars=True)


def test_home_domain_how_uses_runtime_copy_trap(tmp_path: Path) -> None:
    how_domain = tmp_path / "home" / "how_domain" / "workspace"
    how_domain.mkdir(parents=True)
    (how_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    provider = HomeDomainHowProvider(home)

    guidance = _run_copy_trap_after_runtime_exception(
        lambda: provider.guidance_for(("workspace",)),
        home=home,
    )

    assert guidance == ("workspace guidance",)


def test_home_action_how_uses_runtime_copy_trap(tmp_path: Path) -> None:
    actions = tmp_path / "home" / "how_action" / "workspace"
    actions.mkdir(parents=True)
    (actions / "rewrite.md").write_text("rewrite guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    provider = HomeActionHowProvider(home)

    guidance = _run_copy_trap_after_runtime_exception(
        lambda: provider.guidance_for(
            domain="workspace",
            action_name="workspace.rewrite",
        ),
        home=home,
    )

    assert guidance.domain == ()
    assert guidance.action == ("rewrite guidance",)
    assert (
        tmp_path
        / "runtime"
        / "home"
        / "how_action"
        / "workspace"
        / "rewrite.md"
    ).is_file()

def test_home_action_how_includes_domain_and_action_how(tmp_path: Path) -> None:
    how_domain = tmp_path / "home" / "how_domain" / "workspace"
    how_action = tmp_path / "home" / "how_action" / "workspace"
    how_domain.mkdir(parents=True)
    how_action.mkdir(parents=True)
    (how_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    (how_action / "rewrite.md").write_text("rewrite guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    provider = HomeActionHowProvider(home)

    guidance = _run_copy_trap_after_runtime_exception(
        lambda: provider.guidance_for(
            domain="workspace",
            action_name="workspace.rewrite",
        ),
        home=home,
    )

    assert guidance.domain == ("workspace guidance",)
    assert guidance.action == ("rewrite guidance",)


def test_missing_home_prompt_mount_is_optional(tmp_path: Path) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()


    assert HomeDomainHowProvider(home).guidance_for(("workspace",)) == ()
    assert HomeActionHowProvider(home).guidance_for(
        domain="workspace",
        action_name="workspace.rewrite",
    ).domain == ()


def test_malformed_home_prompt_mount_maps_to_runtime_failure(tmp_path: Path) -> None:
    prompt_mount = tmp_path / "home" / "how_domain" / "workspace" / "DOMAIN.md"
    prompt_mount.parent.mkdir(parents=True)
    prompt_mount.write_bytes(b"\xff")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.ensure_runtime_copy(home.parse_link("home:how_domain:workspace"))

    with pytest.raises(RuntimeException) as raised:
        HomeDomainHowProvider(home).guidance_for(("workspace",))

    assert raised.value.reason == RUNTIME_TURN_END
    assert raised.value.payload["kind"] == AgentHomeFailureKind.CONTRACT_VIOLATION.value
    assert raised.value.payload["domain"] == "workspace"
    assert raised.value.payload["error_type"] == "AgentHomeContractError"


def test_home_prompt_mount_io_error_maps_to_runtime_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    def fail_guidance(_self: AgentHomeEngine, _domain: str) -> str | None:
        raise AgentHomeIOError("unavailable")

    monkeypatch.setattr(AgentHomeEngine, "guidance_for_domain", fail_guidance)

    with pytest.raises(RuntimeException) as raised:
        HomeDomainHowProvider(home).guidance_for(("workspace",))

    assert raised.value.reason == RUNTIME_TURN_END
    assert raised.value.payload["kind"] == AgentHomeFailureKind.IO_FAILED.value
    assert raised.value.payload["domain"] == "workspace"


def test_home_runtime_copy_failure_ends_nearest_turn(tmp_path: Path) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn")
        .push(RunLevel.PHASE, "phase2")
    )

    result = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:how_domain:missing"},
            scope=scope,
        )
    )

    assert result.transfer.action is RuntimeTransferAction.END
    assert result.transfer.target == scope.nearest(RunLevel.TURN)

def test_home_runtime_copy_required_payload_contains_paths(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "how" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    executor = HomeResourceReadExecutor(home)

    try:
        executor.execute(
            _execution(
                "home.resource.read",
                {"link": "home:how/refactor/references/checklist.md"},
            ),
            ActionExecutionContext(),
        )
    except RuntimeException as exc:
        assert exc.reason == HOME_RUNTIME_COPY_REQUIRED
        assert exc.payload["link"] == "home:how/refactor/references/checklist.md"
        assert exc.payload["error_type"] == "AgentHomeRuntimeCopyRequired"
        source_path = exc.payload["source_path"]
        runtime_path = exc.payload["runtime_path"]
        assert isinstance(source_path, str)
        assert isinstance(runtime_path, str)
        assert str(tmp_path / "home" / "how" / "refactor") in source_path
        assert str(tmp_path / "runtime" / "home" / "how" / "refactor") in runtime_path
    else:
        raise AssertionError("home.resource.read should require runtime copy")


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
    while True:
        try:
            return callback()
        except AgentHomeRuntimeCopyRequired as exc:
            _handle_copy_trap(
                home,
                message=str(exc),
                payload=exc.to_payload(),
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
