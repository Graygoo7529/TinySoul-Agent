from __future__ import annotations

from datetime import date
from pathlib import Path, PurePosixPath
import re

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
    HomeResourceLink,
    HomeTopLink,
)
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus


_HOME_REFERENCE = re.compile(r"<(home:[^>\s]+)>")
_EXPECTED_TOP_LINKS = {
    "home:agent@AGENT.md",
    "home:agent@user/user.md",
    "home:how@tinysoul-docs",
    "home:what@concept/context-and-links.md",
    "home:what@concept/daily-lifecycle.md",
    "home:what@entity/tiny-soul.md",
    "home:why@why-is-updating-home-important.md",
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
        "home:what@concept/context-and-links.md",
        "home:what@concept/daily-lifecycle.md",
        "home:what@entity/tiny-soul.md",
        "home:why@why-is-updating-home-important.md",
    }.issubset({item.link for item in result.items})


def test_packaged_default_home_exposes_only_context_visible_load_targets(
    tmp_path: Path,
) -> None:
    _, home = _initialized_home(tmp_path)
    provider = HomeBackgroundEntryProvider(home)
    catalog = provider.catalog(date(2026, 7, 15))

    assert catalog.default_links == (
        "home:agent@AGENT.md",
        "home:agent@user/user.md",
    )
    assert catalog.evictable_default_links == ()
    assert [(item.link, item.title) for item in catalog.items] == [
        ("home:how@tinysoul-docs", "TinySoul Documentation")
    ]

    targets = (
        "home:what@entity/tiny-soul.md",
        "home:why@why-is-updating-home-important.md",
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
    assert "background:home:agent@AGENT.md" in initial_labels
    assert "background:home:agent@user/user.md" in initial_labels
    assert "background:home:what@entity/tiny-soul.md" not in initial_labels
    assert "background:home:why@why-is-updating-home-important.md" not in initial_labels
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
