from __future__ import annotations

from datetime import date
from pathlib import Path, PurePosixPath
import re

from tinysoul.action import builtin_action_catalog_root
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.app import ProjectInitializer
from tinysoul.context import (
    CONTROL_EVICT_BACKGROUND,
    SIGNAL_BACKGROUND_PATCH,
    ContextEngineBuilder,
    PromptBlock,
    TaskPrompt,
)
from tinysoul.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeSettings,
    HomeBackgroundEntryProvider,
    HomeActionHowProvider,
    HomeDomainHowProvider,
    HomeResourceLink,
    HomeTopLink,
)
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus


_HOME_REFERENCE = re.compile(r"<(home:[^>\s]+)>")
_EXPECTED_TOP_LINKS = {
    "home:agent@AGENT",
    "home:agent@context/background",
    "home:agent@context/turn-trace",
    "home:agent@context/working",
    "home:agent@user/user",
    "home:how@tinysoul-docs",
    "home:what@concept/context-and-links",
    "home:what@concept/daily-lifecycle",
    "home:what@entity/tiny-soul",
    "home:why@why-is-updating-home-important",
}


def test_packaged_default_home_is_valid_in_an_isolated_project(
    tmp_path: Path,
) -> None:
    root, home = _initialized_home(tmp_path)

    assert set(home.actual_top_links()) == _EXPECTED_TOP_LINKS
    assert [
        (str(item.link), item.title, item.description)
        for item in home.skill_metadata()
    ] == [
        (
            "home:how@tinysoul-docs",
            "TinySoul Documentation",
            "Navigate TinySoul Context and Link semantics and load the right "
            "top-level knowledge or progressive resource for the current task.",
        )
    ]
    _assert_home_references_exist(root / "home", home)

    result = home.search_top(
        "TinySoul context links daily lifecycle update Home documentation",
        top_k=10,
    )

    assert {
        "home:how@tinysoul-docs",
        "home:what@concept/context-and-links",
        "home:what@concept/daily-lifecycle",
        "home:what@entity/tiny-soul",
        "home:why@why-is-updating-home-important",
    }.issubset({item.link for item in result.items})


def test_packaged_default_home_exposes_only_context_visible_load_targets(
    tmp_path: Path,
) -> None:
    _, home = _initialized_home(tmp_path)
    provider = HomeBackgroundEntryProvider(home)
    catalog = provider.catalog(date(2026, 7, 15))

    assert catalog.default_links == (
        "home:agent@AGENT",
        "home:agent@context/background",
        "home:agent@context/turn-trace",
        "home:agent@context/working",
        "home:agent@user/user",
    )
    assert catalog.evictable_default_links == ()
    assert [(item.link, item.title) for item in catalog.items] == [
        ("home:how@tinysoul-docs", "TinySoul Documentation")
    ]

    targets = (
        "home:what@entity/tiny-soul",
        "home:why@why-is-updating-home-important",
    )
    for link in (*catalog.default_links, *targets):
        home.ensure_runtime_copy(HomeTopLink.parse(link))

    context = (
        ContextEngineBuilder(system_text="You are TinySoul.")
        .add_background_provider(provider)
        .build()
    )
    turn_id = context.begin_turn("Use the referenced TinySoul documentation.")
    context.prepare_default_background(date(2026, 7, 15))

    assert context.background_links() == catalog.default_links
    initial_labels = {
        message.label
        for message in context.compose(
            TaskPrompt(
                guide_blocks=(PromptBlock.from_text("test", "Use the context."),)
            )
        ).messages
    }
    assert "background:catalog:home" in initial_labels
    assert "background:home:agent@AGENT" in initial_labels
    assert "background:home:agent@context/background" in initial_labels
    assert "background:home:agent@context/turn-trace" in initial_labels
    assert "background:home:agent@context/working" in initial_labels
    assert "background:home:agent@user/user" in initial_labels
    assert "background:home:what@entity/tiny-soul" not in initial_labels
    assert "background:home:why@why-is-updating-home-important" not in initial_labels
    assert CONTROL_EVICT_BACKGROUND not in {
        tool.name for tool in context.control_scope().tools
    }

    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test.default_home",
            scope=_phase_scope(turn_id),
            payload={
                "call_id": "load_referenced_top",
                "load_links": list(targets),
                "evict_links": [],
            },
        )
    )

    assert context.consume_signals(bus) == ()
    assert context.background_links() == (*catalog.default_links, *targets)


def test_packaged_default_home_provides_stage4_behavior_guidance(
    tmp_path: Path,
) -> None:
    root, home = _initialized_home(tmp_path)
    with builtin_action_catalog_root() as catalog_root:
        catalog = ActionCatalogLoader().load(catalog_root)
    home.reconcile_prompt_mounts(
        domains=tuple(domain.name for domain in catalog.domains()),
        actions=tuple((action.domain, action.name) for action in catalog.actions()),
    )
    core = (root / "home" / "agent" / "AGENT.md").read_text(encoding="utf-8")
    assert "Make each Agent Cycle advance" in core
    assert "authoritative successful mutation or apply ActionResult" in core

    for domain in ("web", "shell", "workspace"):
        home.ensure_runtime_copy(home.parse_link(f"home:how_domain:{domain}"))
    home.ensure_runtime_copy(
        home.parse_link("home:how_action:workspace/rewrite")
    )
    home.ensure_runtime_copy(home.parse_link("home:how_action:workspace/write"))
    domain_guidance = HomeDomainHowProvider(home).guidance_for(("web", "shell"))
    action_guidance = HomeActionHowProvider(home).guidance_for(
        domain="workspace",
        action_name="workspace.rewrite",
    )
    write_guidance = HomeActionHowProvider(home).guidance_for(
        domain="workspace",
        action_name="workspace.write",
    )

    assert "failure.disposition" in domain_guidance[0]
    assert "stable public URLs" in domain_guidance[0]
    assert "`shell.apply` is the authoritative Workspace commit" in domain_guidance[1]
    assert any("workspace.read" in item for item in action_guidance.domain)
    assert any("complete replacement" in item for item in action_guidance.action)
    assert any("`truncated` metadata" in item for item in action_guidance.action)
    assert any("`workspace:` Links" in item for item in action_guidance.action)
    assert any("complete UTF-8 text artifact" in item for item in write_guidance.action)
    assert any("public URLs" in item for item in write_guidance.action)


def _initialized_home(tmp_path: Path) -> tuple[Path, AgentHomeEngine]:
    root = tmp_path / "project"
    ProjectInitializer().initialize(root)
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=root / "home",
            runtime_root=root / "runtime" / "home",
        )
    ).build()
    return root, home


def _assert_home_references_exist(
    home_root: Path,
    home: AgentHomeEngine,
) -> None:
    top_links = set(home.actual_top_links())
    for document in home_root.rglob("*.md"):
        text = document.read_text(encoding="utf-8")
        for value in _HOME_REFERENCE.findall(text):
            link = home.parse_link(value)
            if isinstance(link, HomeTopLink):
                assert value in top_links, f"Missing top link {value} in {document}"
                continue
            assert isinstance(link, HomeResourceLink)
            relative = PurePosixPath(link.relative_path)
            target = home_root.joinpath(link.space, *relative.parts)
            assert target.is_file(), f"Missing resource link {value} in {document}"


def _phase_scope(turn_id: str) -> RunScope:
    return (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, "phase1")
    )
