from __future__ import annotations

from tinysoul.plugins.home.background import home_segment_registration

from datetime import date
from pathlib import Path, PurePosixPath
import re

from tinysoul.kernel.context import (
    CONTROL_EVICT_BACKGROUND,
    SIGNAL_BACKGROUND_PATCH,
    ContextEngineBuilder,
    PromptBlock,
    TaskPrompt,
)
from tinysoul.plugins.home import (
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeSettings,
    HomeBackgroundEntryProvider,
    HomeResourceLink,
    HomeTopLink,
)
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus
from tests.support.project import copy_initialized_project


_HOME_REFERENCE = re.compile(r"<(home:[^>\s]+)>")
_REQUIRED_TOP_LINKS = {
    "home:agent@AGENT",
    "home:agent@identity/identity",
    "home:agent@identity/soul",
    "home:agent@user/user",
}


def test_packaged_default_home_is_valid_in_an_isolated_project(
    tmp_path: Path,
) -> None:
    root, home = _initialized_home(tmp_path)

    actual_top_links = set(home.actual_top_links())
    assert _REQUIRED_TOP_LINKS <= actual_top_links
    skill_links = {str(item.link) for item in home.skill_metadata()}
    assert skill_links
    assert skill_links <= actual_top_links
    _assert_home_references_exist(root / "home", home)


async def test_packaged_default_home_exposes_only_context_visible_load_targets(
    tmp_path: Path,
) -> None:
    _, home = _initialized_home(tmp_path)
    provider = HomeBackgroundEntryProvider(home)
    catalog = provider.catalog(date(2026, 7, 15))

    assert _REQUIRED_TOP_LINKS <= set(catalog.default_links)
    assert catalog.evictable_default_links == ()
    assert catalog.items

    targets = (catalog.items[0].link,)
    for link in (*catalog.default_links, *targets):
        home.ensure_runtime_copy(HomeTopLink.parse(link))

    context = (
        ContextEngineBuilder(system_text="You are TinySoul.")
        .with_segment(home_segment_registration(home))
        .build()
    )
    turn_id = context.begin_turn("Use the referenced TinySoul documentation.")
    await context.open_segments(date(2026, 7, 15))

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
    assert {
        f"background:{link}" for link in catalog.default_links
    } <= initial_labels
    assert all(
        f"background:{item.link}" not in initial_labels
        for item in catalog.items
    )
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

    assert await context.consume_signals(bus) == ()
    assert context.background_links() == (*catalog.default_links, *targets)


def _initialized_home(tmp_path: Path) -> tuple[Path, AgentHomeEngine]:
    root = tmp_path / "project"
    copy_initialized_project(root)
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
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, "phase1")
    )
