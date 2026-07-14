"""Memory Link, store, search, recall, and Background tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tinysoul.context import ContextEngineBuilder
from tinysoul.home import (
    AgentHomeEngineBuilder,
    AgentHomeSettings,
    HomeBackgroundEntryProvider,
    parse_agent_home_settings,
)
from tinysoul.infra.config import ConfigError
from tinysoul.loop import BusinessDay
from tinysoul.memory import (
    MemoryBackgroundEntryProvider,
    MemoryContractError,
    MemoryEngine,
    MemoryInvariantError,
    MemoryLink,
    MemoryPeriod,
    MemorySearchRequest,
    MemorySearchSettings,
    MemorySections,
    MemorySettings,
    MemoryStore,
    parse_memory_settings,
    render_memory_document,
)
from tinysoul.runtime import RunScope, RuntimeException


class _HomeCatalog:
    def actual_top_links(self) -> tuple[str, ...]:
        return ()


class _Reranker:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid
        self.requests: list[MemorySearchRequest] = []

    def rerank(
        self,
        request: MemorySearchRequest,
        *,
        scope: RunScope,
    ) -> tuple[str, ...] | None:
        self.requests.append(request)
        if not self.valid:
            return ("memory:2099-01-01#morning",)
        return tuple(
            candidate.candidate_id
            for candidate in reversed(request.candidates)
            if candidate.link == request.candidates[-1].link
        )[:1]


def test_memory_link_maps_canonical_date_and_rejects_legacy_forms() -> None:
    link = MemoryLink.parse("memory:2026-07-13")

    assert link.day == date(2026, 7, 13)
    assert link.relative_path == "2026/07/2026-07-13.md"
    assert MemoryLink.from_relative(link.relative_path) == link
    for value in (
        "home:memory@2026-07-13",
        "memory@2026-07-13",
        "memory:2026-02-30",
        "memory:2026-7-13",
        "memory:2026-07-13/part",
    ):
        with pytest.raises(MemoryContractError):
            MemoryLink.parse(value)


def test_empty_memory_store_has_no_read_side_effect_and_recall_is_exact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    memory = _memory(root)

    assert memory.links() == ()
    assert not root.exists()
    with pytest.raises(MemoryContractError, match="does not exist"):
        memory.recall("memory:2026-07-13")
    assert not root.exists()

    _write_memory(root, "2026-07-13", MemorySections(morning="- complete"))
    recalled = memory.recall("memory:2026-07-13")
    assert recalled.link == "memory:2026-07-13"
    assert recalled.day == "2026-07-13"
    assert "## 上午" in recalled.text
    assert recalled.digest


def test_memory_config_is_independent_and_rejects_legacy_home_table(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_agent_home_settings({"memory": {}}, project_root=tmp_path)
    with pytest.raises(ConfigError, match="inside the project root"):
        parse_memory_settings({"root": "../outside"}, project_root=tmp_path)


def test_recall_and_search_reject_existing_corrupt_or_oversized_documents(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    corrupt = root / "2026" / "07" / "2026-07-13.md"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("not a Memory document", encoding="utf-8")
    memory = _memory(root)

    with pytest.raises(MemoryInvariantError):
        memory.recall("memory:2026-07-13")
    with pytest.raises(MemoryInvariantError):
        memory.search("anything")

    corrupt.write_text("x" * 401, encoding="utf-8")
    limited = _memory(root, max_document_chars=400)
    with pytest.raises(MemoryInvariantError, match="exceeds"):
        limited.recall("memory:2026-07-13")


def test_memory_search_selects_best_period_and_deduplicates_dates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    _write_memory(
        root,
        "2026-07-12",
        MemorySections(
            morning="- routine notes",
            afternoon="- special lifecycle decision with details",
        ),
    )
    _write_memory(
        root,
        "2026-07-13",
        MemorySections(
            morning="- special implementation result",
            evening="- unrelated closeout",
        ),
    )
    memory = _memory(root, summary_max_chars=18)

    result = memory.search("special", top_k=2)

    assert len(result.items) == 2
    assert len({item.link for item in result.items}) == 2
    day12 = next(item for item in result.items if item.day == "2026-07-12")
    assert day12.period is MemoryPeriod.AFTERNOON
    assert len(day12.summary) <= 18
    assert all(item.link.startswith("memory:") for item in result.items)


def test_memory_search_reranker_is_candidate_only_and_falls_back(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    _write_memory(root, "2026-07-12", MemorySections(morning="- shared alpha"))
    _write_memory(root, "2026-07-13", MemorySections(morning="- shared beta"))
    memory = _memory(root)
    scope = RunScope()
    valid = _Reranker(valid=True)

    reranked = memory.search("shared", top_k=2, reranker=valid, scope=scope)
    fallback = memory.search(
        "shared",
        top_k=2,
        reranker=_Reranker(valid=False),
        scope=scope,
    )

    assert reranked.reranked is True
    assert len(reranked.items) == 1
    assert valid.requests
    assert fallback.reranked is False
    assert len(fallback.items) == 2


def test_context_loads_only_exact_yesterday_and_pressure_evicts_memory(
    tmp_path: Path,
) -> None:
    home_root = tmp_path / "home"
    core = home_root / "agent" / "AGENT.md"
    core.parent.mkdir(parents=True)
    core.write_text("# Agent\n\nCore identity.", encoding="utf-8")
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.ensure_runtime_copy(home.parse_link("home:agent@core"))
    memory_root = tmp_path / "memory"
    _write_memory(memory_root, "2026-07-12", MemorySections(morning="- older"))
    _write_memory(memory_root, "2026-07-13", MemorySections(morning="- yesterday"))
    memory = _memory(memory_root)
    context = (
        ContextEngineBuilder(system_text="system")
        .add_background_provider(HomeBackgroundEntryProvider(home))
        .add_background_provider(MemoryBackgroundEntryProvider(memory))
        .build()
    )

    context.begin_turn("first")
    context.prepare_default_background(date(2026, 7, 14))
    assert context.background_links() == (
        "home:agent@core",
        "memory:2026-07-13",
    )
    report = context.reclaim_pressure(required_chars=1)
    assert report.evicted_background_links == ("memory:2026-07-13",)
    assert context.background_links() == ("home:agent@core",)
    context.end_turn()

    context.begin_turn("second")
    context.prepare_default_background(date(2026, 7, 14))
    assert "memory:2026-07-13" in context.background_links()


def test_corrupt_yesterday_memory_ends_turn_instead_of_looking_older(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memory"
    _write_memory(root, "2026-07-12", MemorySections(morning="- older"))
    target = root / "2026" / "07" / "2026-07-13.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("corrupt", encoding="utf-8")
    context = (
        ContextEngineBuilder(system_text="system")
        .add_background_provider(MemoryBackgroundEntryProvider(_memory(root)))
        .build()
    )
    context.begin_turn("test")

    with pytest.raises(RuntimeException) as raised:
        context.prepare_default_background(date(2026, 7, 14))

    assert raised.value.payload["kind"] == "memory.internal_failure"
    assert "memory:2026-07-12" not in context.background_links()


def _memory(
    root: Path,
    *,
    max_document_chars: int = 16000,
    summary_max_chars: int = 320,
) -> MemoryEngine:
    return MemoryEngine(
        settings=MemorySettings(
            root=root,
            max_document_chars=max_document_chars,
            search=MemorySearchSettings(summary_max_chars=summary_max_chars),
        ),
        home_catalog=_HomeCatalog(),
    )


def _write_memory(root: Path, value: str, sections: MemorySections) -> None:
    day = BusinessDay.parse(value)
    MemoryStore(root=root, max_document_chars=16000).write(
        MemoryLink(day.value),
        render_memory_document(day, sections),
    )
