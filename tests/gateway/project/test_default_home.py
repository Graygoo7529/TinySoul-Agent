from __future__ import annotations

from tinysoul.plugins.home.services import HomeService
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
    HomeResourceRef,
    HomeTopRef,
)
from tinysoul.runtime import RunLevel, RunScope, Signal, SignalBus
from tests.support.project import copy_initialized_project

_HOME_REFERENCE = re.compile(r"<(home:[^>\s]+)>")
_REQUIRED_TOP_LINKS = {
    "home:top/agent/AGENT",
    "home:top/agent/identity/identity",
    "home:top/agent/identity/soul",
    "home:top/agent/user/user",
}


def test_packaged_default_home_is_valid_in_an_isolated_project(
    tmp_path: Path,
) -> None:
    root, home = _initialized_home(tmp_path)

    actual_top_refs = set(home.actual_top_refs())
    assert _REQUIRED_TOP_LINKS <= actual_top_refs
    skill_links = {str(item.ref) for item in home.skill_metadata()}
    assert skill_links
    assert skill_links <= actual_top_refs
    _assert_home_references_exist(root / "home", home)


async def test_packaged_default_home_exposes_only_context_visible_load_targets(
    tmp_path: Path,
) -> None:
    _, home = _initialized_home(tmp_path)
    provider = HomeBackgroundEntryProvider(HomeService(home))
    catalog = await provider.catalog(date(2026, 7, 15))

    assert _REQUIRED_TOP_LINKS <= set(catalog.default_refs)
    assert catalog.evictable_default_refs == ()
    assert catalog.items

    targets = (catalog.items[0].ref,)
    for ref in (*catalog.default_refs, *targets):
        home.ensure_runtime_copy(HomeTopRef.parse(ref))

    context = (
        ContextEngineBuilder(system_text="You are TinySoul.")
        .with_segment(home_segment_registration(HomeService(home)))
        .build()
    )
    turn_id = context.begin_turn(
        "Use the referenced TinySoul documentation.", turn_id="2026-10-06/70"
    )
    await context.open_segments(date(2026, 7, 15))

    assert context.background_refs() == catalog.default_refs
    initial_labels = {
        message.label
        for message in context.compose(
            TaskPrompt(
                guide_blocks=(PromptBlock.from_text("test", "Use the context."),)
            )
        ).messages
    }
    assert "background:catalog:home" in initial_labels
    assert {f"background:{ref}" for ref in catalog.default_refs} <= initial_labels
    assert all(f"background:{item.ref}" not in initial_labels for item in catalog.items)
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
                "load_refs": list(targets),
                "evict_refs": [],
            },
        )
    )

    assert await context.consume_signals(bus) == ()
    assert context.background_refs() == (*catalog.default_refs, *targets)


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
    top_links = set(home.actual_top_refs())
    for document in home_root.rglob("*.md"):
        text = document.read_text(encoding="utf-8")
        for value in _HOME_REFERENCE.findall(text):
            ref = home.parse_ref(value)
            if isinstance(ref, HomeTopRef):
                assert value in top_links, f"Missing top ref {value} in {document}"
                continue
            assert isinstance(ref, HomeResourceRef)
            relative = PurePosixPath(ref.relative_path)
            target = home_root.joinpath(ref.space, *relative.parts)
            assert target.is_file(), f"Missing resource ref {value} in {document}"


def _phase_scope(turn_id: str) -> RunScope:
    return (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, "phase1")
    )
