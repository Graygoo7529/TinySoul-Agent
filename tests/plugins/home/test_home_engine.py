from __future__ import annotations

from collections.abc import Callable, Awaitable
from datetime import date
from pathlib import Path
from typing import TypeVar

import pytest
from tinysoul.plugins.home.services import HomeService
from tinysoul.plugins.home.links import parse_home_link

from tinysoul.kernel.action.call import ActionCall, ActionExecution
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.execution.executor import ActionExecutionContext
from tinysoul.kernel.action.result import ActionResultStatus
from tinysoul.kernel.action.catalog.specs import (
    ActionExecutionSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.plugins.home import (
    AgentHomeContractError,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeFailureKind,
    AgentHomeIOError,
    AgentHomeRuntimeCopyRequired,
    AgentHomeRuntimeCopyTrapHandler,
    AgentHomeSettings,
    HomeActionSkillProvider,
    HomeBackgroundContentLoader,
    HomeBackgroundEntryProvider,
    HomeDomainSkillProvider,
    HomeInspectExecutor,
    HomePromptMountWriteExecutor,
    HomeTopWriteExecutor,
    HomeTopLink,
)
from tinysoul.plugins.home.background import (
    ActualHomeBackgroundEntryProvider,
    home_segment_registration,
)
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.context.background import BackgroundPatch
from tinysoul.kernel.context.signals import build_background_patch_signal
from tinysoul.kernel.loop.context_signals import ContextSignalConsumer
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.plugins.home.failures import HOME_RUNTIME_COPY_REQUIRED
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeModuleRunner,
    RuntimeTrap,
    Signal,
    SignalBus,
    TrapHandlerRegistry,
    RuntimeTransferAction,
    TrapSnap,
)

T = TypeVar("T")
_SKILL_TEXT = (
    "---\n"
    "title: Refactor\n"
    "description: Apply the refactoring workflow.\n"
    "---\n\n"
    "# Refactor\n"
)


def test_home_settings_reject_overlapping_original_and_runtime_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match="must not overlap"):
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "home" / "runtime",
        )


def test_home_top_links_use_extensionless_identity_and_markdown_mapping(
    tmp_path: Path,
) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    cases = {
        "home:agent@AGENT": "agent/AGENT.md",
        "home:agent@identity/identity": "agent/identity/identity.md",
        "home:agent@identity/soul": "agent/identity/soul.md",
        "home:agent@context/turn-trace": "agent/context/turn-trace.md",
        "home:agent@user/user": "agent/user/user.md",
        "home:skills@python-refactor": "skills/python-refactor/SKILL.md",
    }

    for value, expected in cases.items():
        link = HomeTopLink.parse(value)
        assert home.layout.relative_for_top(link) == expected
        assert home.layout.top_link_for_relative(expected) == link

    for legacy in (
        "home:agent@AGENT.md",
        "home:skills@python-refactor.md",
        "home:skills@python/refactor",
        "home:what@entity/tiny-soul",
        "home:why@context-budget",
    ):
        with pytest.raises(AgentHomeContractError):
            HomeTopLink.parse(legacy)


def test_top_files_cannot_be_addressed_as_progressive_resources(
    tmp_path: Path,
) -> None:
    files = {
        "agent/AGENT.md": "core",
        "skills/refactor/SKILL.md": _SKILL_TEXT,
    }
    for relative, text in files.items():
        path = tmp_path / "home" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    aliases = (
        "home:agent/AGENT.md",
        "home:what/entity/tiny-soul.md",
        "home:why/question.md",
        "home:skills/refactor/SKILL.md",
    )
    for alias in aliases:
        with pytest.raises(AgentHomeContractError, match="Home"):
            home.read_resource(alias)
        with pytest.raises(AgentHomeContractError, match="Home"):
            home.write_resource(alias, "replacement", overwrite=True)


async def test_home_background_is_copied_only_when_context_loads_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "home" / "agent" / "context" / "project.md"
    source.parent.mkdir(parents=True)
    source.write_text("project knowledge", encoding="utf-8")
    core = tmp_path / "home" / "agent" / "AGENT.md"
    core.write_text("core identity", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    link = "home:agent@context/project"
    context = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(home_segment_registration(HomeService(home)))
        .build()
    )
    turn_id = context.begin_turn("load project background")
    home.ensure_runtime_copy(HomeTopLink.parse("home:agent@AGENT"))
    await context.open_segments(date(2026, 7, 14))
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
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
    runtime_path = tmp_path / "runtime" / "home" / "agent" / "context" / "project.md"
    assert not runtime_path.exists()
    late_signal = build_background_patch_signal(
        BackgroundPatch(evict_links=(link,)),
        call_id="evict_later",
        scope=scope,
        source="test",
    )
    take_namespace = bus.consume_namespace

    def take_then_receive_later(prefix: str) -> tuple[Signal, ...]:
        signals = take_namespace(prefix)
        bus.emit(late_signal)
        return signals

    monkeypatch.setattr(bus, "consume_namespace", take_then_receive_later)
    bus.emit(
        build_background_patch_signal(
            BackgroundPatch(load_links=(link,)),
            call_id="load_project",
            scope=scope,
            source="test",
        )
    )

    assert await consumer.consume(scope=scope) == ()

    assert runtime_path.read_text(encoding="utf-8") == "project knowledge"
    assert link in context.background_links()
    assert late_signal in bus.peek()


async def test_home_provides_default_background_without_exposing_domain_skills(
    tmp_path: Path,
) -> None:
    agent = tmp_path / "home" / "agent"
    agent.mkdir(parents=True)
    (agent / "AGENT.md").write_text("core rules", encoding="utf-8")
    skills_domain = tmp_path / "home" / "skills_domain" / "workspace"
    skills_domain.mkdir(parents=True)
    (skills_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)

    defaults = _run_copy_trap_after_runtime_exception(
        home.default_background_entries,
        home=home,
    )
    loadable = home.loadable_background_links()
    guidance = await _run_async_copy_trap(
        lambda: HomeDomainSkillProvider(HomeService(home)).guidance_for(("workspace",)),
        home=home,
    )

    assert defaults[0].link == "home:agent@AGENT"
    assert defaults[0].content == "core rules"
    assert "home:skills_domain:workspace" not in loadable
    assert guidance == ("workspace guidance",)
    assert (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").is_file()
    assert (
        tmp_path / "runtime" / "home" / "skills_domain" / "workspace" / "DOMAIN.md"
    ).is_file()


def test_home_runtime_copy_can_be_prepared_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "home" / "skills" / "refactor"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_SKILL_TEXT, encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    home.ensure_runtime_copy(HomeTopLink("skills", "refactor"))

    assert (
        tmp_path / "runtime" / "home" / "skills" / "refactor" / "SKILL.md"
    ).read_text(encoding="utf-8") == _SKILL_TEXT


async def test_home_background_provider_catalog_does_not_materialize_core(
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
    provider = HomeBackgroundEntryProvider(HomeService(home))

    catalog = await provider.catalog(date(2026, 7, 14))

    assert catalog.default_links == ("home:agent@AGENT",)
    assert not (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").exists()

    with pytest.raises(RuntimeException):
        await provider.load("home:agent@AGENT", date(2026, 7, 14))
    home.ensure_runtime_copy(home.parse_link("home:agent@AGENT"))
    content = await provider.load("home:agent@AGENT", date(2026, 7, 14))

    assert content == "core rules"
    assert (tmp_path / "runtime" / "home" / "agent" / "AGENT.md").is_file()


async def test_actual_home_background_provider_ignores_runtime_overrides(
    tmp_path: Path,
) -> None:
    agent = tmp_path / "home" / "agent"
    agent.mkdir(parents=True)
    (agent / "AGENT.md").write_text("actual rules", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.write_top("home:agent@AGENT", "runtime rules", overwrite=True)

    user_provider = HomeBackgroundEntryProvider(HomeService(home))
    reflection_provider = ActualHomeBackgroundEntryProvider(HomeService(home))
    day = date(2026, 8, 3)

    assert await user_provider.load("home:agent@AGENT", day) == "runtime rules"
    assert (await reflection_provider.catalog(day)).default_links == (
        "home:agent@AGENT",
    )
    assert await reflection_provider.load("home:agent@AGENT", day) == "actual rules"


async def test_home_background_provider_automatically_loads_allowlisted_agent_tops(
    tmp_path: Path,
) -> None:
    agent = tmp_path / "home" / "agent"
    extra = agent / "context" / "extra.md"
    working = agent / "context" / "working.md"
    user = agent / "user" / "user.md"
    working.parent.mkdir(parents=True)
    user.parent.mkdir(parents=True)
    (agent / "AGENT.md").write_text("core rules", encoding="utf-8")
    extra.write_text("on-demand rules", encoding="utf-8")
    working.write_text("working rules", encoding="utf-8")
    user.write_text("user facts", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    provider = HomeBackgroundEntryProvider(HomeService(home))

    catalog = await provider.catalog(date(2026, 7, 14))

    assert catalog.default_links == (
        "home:agent@AGENT",
        "home:agent@context/working",
        "home:agent@user/user",
    )
    assert catalog.evictable_default_links == ()
    assert "home:agent@context/extra" in catalog.loadable_links
    assert "home:agent@context/extra" not in catalog.default_links
    assert not (tmp_path / "runtime" / "home" / "agent").exists()

    home.delete_top("home:agent@user/user")

    assert (await provider.catalog(date(2026, 7, 15))).default_links == (
        "home:agent@AGENT",
        "home:agent@context/working",
    )


def test_home_runtime_copy_trap_prepares_copy_and_retries_current_frame(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "skills" / "refactor"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_SKILL_TEXT, encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, "turn")
        .push(RunLevel.PHASE, "phase3")
    )

    result = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:skills@refactor"},
            scope=scope,
        )
    )

    assert result.transfer.action is RuntimeTransferAction.RETRY
    assert result.transfer.target == scope.current()
    assert (
        tmp_path / "runtime" / "home" / "skills" / "refactor" / "SKILL.md"
    ).is_file()

    repeated = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy still required",
            payload={"link": "home:skills@refactor"},
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
    link = HomeTopLink("agent", "AGENT")
    home.ensure_runtime_copy(link)
    runtime = tmp_path / "runtime" / "home" / "agent" / "AGENT.md"
    runtime.unlink()
    scope = RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, "turn")

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


async def test_home_resource_read_executor_returns_bounded_text(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "skills" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    execution = _execution(
        "home.inspect",
        {"ref": "home:skills/refactor/references/checklist.md", "max_chars": 512},
    )

    executor = HomeInspectExecutor(HomeService(home))
    home.ensure_runtime_copy(
        parse_home_link("home:skills/refactor/references/checklist.md")
    )
    with_runtime_copy = await executor.execute(execution, ActionExecutionContext())

    assert with_runtime_copy.status is ActionResultStatus.SUCCESS
    assert with_runtime_copy.payload["items"] == [
        {"ref": "home:skills/refactor/references/checklist.md#L1-L1", "text": "abcdef"}
    ]


async def test_home_resource_read_rejects_prompt_mount_spaces(tmp_path: Path) -> None:
    skills_domain = tmp_path / "home" / "skills_domain" / "workspace"
    skills_action = tmp_path / "home" / "skills_action" / "workspace"
    skills_domain.mkdir(parents=True)
    skills_action.mkdir(parents=True)
    (skills_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    (skills_action / "compose.md").write_text("rewrite guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    for link in (
        "home:skills_domain:workspace",
        "home:skills_action:workspace/compose",
        "home:skills_domain/workspace/DOMAIN.md",
        "home:skills_action/workspace/compose.md",
    ):
        result = await HomeInspectExecutor(HomeService(home)).execute(
            _execution("home.inspect", {"ref": link}),
            ActionExecutionContext(),
        )

        assert result.status is ActionResultStatus.FAILED
        assert result.failure is not None
        assert result.failure.reason == "invalid_inspect"


async def test_home_resource_read_rejects_non_positive_limit(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "skills" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    result = await HomeInspectExecutor(HomeService(home)).execute(
        _execution(
            "home.inspect",
            {"ref": "home:skills/refactor/references/checklist.md", "max_chars": 0},
        ),
        ActionExecutionContext(),
    )

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == "invalid_inspect"


async def test_home_top_and_prompt_mount_write_executors_use_home_mutation_boundary(
    tmp_path: Path,
) -> None:
    bus = SignalBus()
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)

    missing_kind = await HomeTopWriteExecutor(HomeService(home)).execute(
        _execution(
            "home.top.write",
            {"link": "home:agent@project", "text": "project"},
        ),
        ActionExecutionContext(signal_bus=bus),
    )
    created = await HomeTopWriteExecutor(HomeService(home)).execute(
        _execution(
            "home.top.write",
            {
                "link": "home:agent@project",
                "text": "project",
            },
        ),
        ActionExecutionContext(signal_bus=bus),
    )
    prompt = await HomePromptMountWriteExecutor(HomeService(home)).execute(
        _execution(
            "home.prompt_mount.write",
            {
                "link": "home:skills_domain:workspace",
                "text": "workspace guidance",
            },
        ),
        ActionExecutionContext(signal_bus=bus),
    )

    assert [signal.name for signal in bus.peek()] == ["context.home.update"]
    assert missing_kind.status is ActionResultStatus.SUCCESS
    assert missing_kind.payload["state"] == "created"
    assert created.status is ActionResultStatus.FAILED
    assert prompt.status is ActionResultStatus.SUCCESS
    assert home.read_top("home:agent@project") == "project"
    assert home.guidance_for_domain("workspace") == "workspace guidance"


def test_home_engine_resource_read_rejects_bool_limit(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "skills" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    with pytest.raises(AgentHomeContractError, match="positive"):
        home.read_resource(
            "home:skills/refactor/references/checklist.md", max_chars=True
        )


async def test_home_domain_skills_uses_runtime_copy_trap(tmp_path: Path) -> None:
    skills_domain = tmp_path / "home" / "skills_domain" / "workspace"
    skills_domain.mkdir(parents=True)
    (skills_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)
    provider = HomeDomainSkillProvider(HomeService(home))

    guidance = await _run_async_copy_trap(
        lambda: provider.guidance_for(("workspace",)),
        home=home,
    )

    assert guidance == ("workspace guidance",)


async def test_home_action_skills_uses_runtime_copy_trap(tmp_path: Path) -> None:
    actions = tmp_path / "home" / "skills_action" / "workspace"
    actions.mkdir(parents=True)
    (actions / "compose.md").write_text("rewrite guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)
    provider = HomeActionSkillProvider(HomeService(home))

    guidance = await _run_async_copy_trap(
        lambda: provider.guidance_for(
            domain="workspace",
            action_name="workspace.compose",
        ),
        home=home,
    )

    assert guidance.domain == ()
    assert guidance.action == ("rewrite guidance",)
    assert (
        tmp_path / "runtime" / "home" / "skills_action" / "workspace" / "compose.md"
    ).is_file()


async def test_home_action_skills_includes_domain_and_action_skills(
    tmp_path: Path,
) -> None:
    skills_domain = tmp_path / "home" / "skills_domain" / "workspace"
    skills_action = tmp_path / "home" / "skills_action" / "workspace"
    skills_domain.mkdir(parents=True)
    skills_action.mkdir(parents=True)
    (skills_domain / "DOMAIN.md").write_text("workspace guidance", encoding="utf-8")
    (skills_action / "compose.md").write_text("rewrite guidance", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)
    provider = HomeActionSkillProvider(HomeService(home))

    guidance = await _run_async_copy_trap(
        lambda: provider.guidance_for(
            domain="workspace",
            action_name="workspace.compose",
        ),
        home=home,
    )

    assert guidance.domain == ("workspace guidance",)
    assert guidance.action == ("rewrite guidance",)


async def test_missing_home_prompt_mount_is_optional(tmp_path: Path) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)

    assert (
        await HomeDomainSkillProvider(HomeService(home)).guidance_for(("workspace",))
        == ()
    )
    assert (
        await HomeActionSkillProvider(HomeService(home)).guidance_for(
            domain="workspace",
            action_name="workspace.compose",
        )
    ).domain == ()


async def test_malformed_home_prompt_mount_maps_to_runtime_failure(
    tmp_path: Path,
) -> None:
    prompt_mount = tmp_path / "home" / "skills_domain" / "workspace" / "DOMAIN.md"
    prompt_mount.parent.mkdir(parents=True)
    prompt_mount.write_bytes(b"\xff")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    _bind_workspace_mounts(home)
    home.ensure_runtime_copy(home.parse_link("home:skills_domain:workspace"))

    with pytest.raises(RuntimeException) as raised:
        await HomeDomainSkillProvider(HomeService(home)).guidance_for(("workspace",))

    assert raised.value.reason == RUNTIME_TURN_END
    assert raised.value.payload["kind"] == AgentHomeFailureKind.CONTRACT_VIOLATION.value
    assert raised.value.payload["domain"] == "workspace"
    assert raised.value.payload["error_type"] == "AgentHomeContractError"


async def test_home_prompt_mount_io_error_maps_to_runtime_failure(
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
        await HomeDomainSkillProvider(HomeService(home)).guidance_for(("workspace",))

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
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, "turn")
        .push(RunLevel.PHASE, "phase2")
    )

    result = AgentHomeRuntimeCopyTrapHandler(home).handle(
        TrapSnap(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:skills_domain:missing"},
            scope=scope,
        )
    )

    assert result.transfer.action is RuntimeTransferAction.END
    assert result.transfer.target == scope.nearest(RunLevel.TURN)


async def test_home_inspect_reads_source_without_runtime_copy(tmp_path: Path) -> None:
    ref = tmp_path / "home" / "skills" / "refactor" / "references"
    ref.mkdir(parents=True)
    (ref / "checklist.md").write_text("abcdef", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home", runtime_root=tmp_path / "runtime" / "home"
        )
    ).build()
    result = await HomeInspectExecutor(HomeService(home)).execute(
        _execution(
            "home.inspect", {"ref": "home:skills/refactor/references/checklist.md"}
        ),
        ActionExecutionContext(),
    )
    assert result.status is ActionResultStatus.SUCCESS


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
                            "ref": {"type": "string"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["ref"],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(),
                execution=ActionExecutionSpec(
                    executor=action_name,
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
        .push(RunLevel.AGENT, "program")
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


def _bind_workspace_mounts(home: AgentHomeEngine) -> None:
    home.reconcile_prompt_mounts(
        domains=("workspace",),
        actions=(("workspace", "workspace.compose"),),
    )


async def _run_async_copy_trap(
    callback: Callable[[], Awaitable[T]], *, home: AgentHomeEngine
) -> T:
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, "turn")
        .push(RunLevel.PHASE, "phase")
    )
    while True:
        try:
            return await callback()
        except RuntimeException as exc:
            assert exc.reason == HOME_RUNTIME_COPY_REQUIRED
            _handle_copy_trap(
                home, message=exc.message, payload=exc.payload, scope=scope
            )
