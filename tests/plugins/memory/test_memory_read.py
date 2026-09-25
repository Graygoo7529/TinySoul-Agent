from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.memory.services import MemoryService
from tinysoul.infra.references import ReferenceResolver, ResourceTarget
from tinysoul.kernel.retrieval.contracts import (
    BacklinkSearch,
    SearchOptions,
    SearchFailure,
)
from tinysoul.plugins.memory import (
    ActiveMemoryBackgroundEntryProvider,
    ConceptMemoryDocument,
    DailyMemoryDocument,
    EntityMemoryDocument,
    FactMemoryDocument,
    MemoryConfidence,
    MemoryContractError,
    MemoryEngine,
    MemoryInspectSettings,
    MemoryInvariantError,
    MemoryIOError,
    MemoryKind,
    MemoryLink,
    MemoryPatchKind,
    MemoryPatchOperation,
    MemorySettings,
    MemoryStatus,
    NoteMemoryDocument,
    parse_memory_settings,
)


DAY = CalendarDay.parse("2026-07-12")
NEXT_DAY = CalendarDay.parse("2026-07-13")


def test_five_kind_links_are_canonical_and_map_to_stable_paths() -> None:
    assert MemoryLink.parse("memory:daily/2026-07-12").relative_path == (
        "daily/2026/07/2026-07-12.md"
    )
    assert MemoryLink.parse("memory:entity/graygoo").relative_path == (
        "entity/graygoo.md"
    )
    assert MemoryLink.parse("memory:concept/agent-design").relative_path == (
        "concept/agent-design.md"
    )
    assert MemoryLink.parse("memory:fact/f-a71c9d2e5f42").kind is MemoryKind.FACT
    assert MemoryLink.parse("memory:note/n-a71c9d2e5f42").kind is MemoryKind.NOTE

    for invalid in (
        "memory:current",
        "memory:yesterday",
        "memory:entity/GrayGoo",
        "memory:fact/f-readable-name",
        "memory:daily/2026-7-12",
    ):
        with pytest.raises(MemoryContractError):
            MemoryLink.parse(invalid)
    with pytest.raises(MemoryContractError, match="120"):
        MemoryLink(MemoryKind.ENTITY, "a" * 121)


def test_document_dates_headings_and_redirect_kinds_are_strict() -> None:
    with pytest.raises(MemoryContractError, match="target day"):
        replace(_daily(DAY.value), updated_on=NEXT_DAY.value)
    with pytest.raises(MemoryContractError, match="level-1"):
        replace(_daily(DAY.value), content="Title\n===")
    with pytest.raises(MemoryContractError, match="same kind"):
        replace(
            _entity("old-entity"),
            status=MemoryStatus.MERGED,
            redirect_to=MemoryLink.parse("memory:concept/new-concept"),
            content="Merged into a replacement concept.",
        )


async def test_active_memory_and_non_evictable_current_latest_background(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "runtime" / "session"
    session_root.mkdir(parents=True)
    memory = _memory(tmp_path, session_root=session_root)
    initial = memory.initialize_active_day(NEXT_DAY)
    assert initial.content == ""

    patched = memory.patch_active(
        day=NEXT_DAY,
        operations=(
            MemoryPatchOperation(
                MemoryPatchKind.APPEND,
                text="Continue memory:concept/agent-design tomorrow.",
            ),
        ),
    )
    assert "memory:concept/agent-design" in patched.content

    memory.write_document(_daily(DAY.value))
    provider = ActiveMemoryBackgroundEntryProvider(MemoryService(memory))
    catalog = await provider.catalog(NEXT_DAY.value)
    assert catalog.default_links == ("memory:current", "memory:latest")
    assert catalog.evictable_default_links == ()
    assert patched.content in await provider.load("memory:current", NEXT_DAY.value)
    latest = await provider.load("memory:latest", NEXT_DAY.value)
    assert "memory:daily/2026-07-12" in latest
    assert "Daily evidence" in latest


def test_single_document_write_requires_existing_references(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    concept = _concept("memory-systems")
    note = _note(
        "n-b71c9d2e5f42", "Memory systems", relations=(concept.link,), evidence=()
    )
    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(note)
    memory.write_document(concept)
    memory.write_document(note)
    missing = _note(
        "n-c71c9d2e5f42",
        "Broken note",
        evidence=(),
        relations=(MemoryLink.parse("memory:concept/missing"),),
    )
    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(missing)
    metadata = memory.inspect(str(note.link))["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["display"] == "Memory systems"
    assert memory.read_document(concept.link).document == concept


def test_memory_config_uses_current_sections_and_rejects_old_names(
    tmp_path: Path,
) -> None:
    settings = parse_memory_settings(
        {
            "root": "memory",
            "max_active_chars": 1000,
            "inspect": {"page_max_chars": 4096},
            "semantic_search": {"embedding_cache_max_chars": 123456},
        },
        project_root=tmp_path,
    )
    assert settings.root == (tmp_path / "memory").resolve()
    assert settings.inspect.page_max_chars == 4096
    assert settings.semantic_search.embedding_cache_max_chars == 123456
    with pytest.raises(Exception):
        parse_memory_settings({"search": {}}, project_root=tmp_path)


def test_all_active_relation_targets_resolve_to_active_entity_or_concept(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    daily = _daily(DAY.value)
    fact = _fact(
        "f-a1b2c3d4e5f6",
        "A relation target fact.",
        relations=(),
        evidence=(daily.link,),
    )
    memory.write_document(daily)
    memory.write_document(fact)
    old = replace(
        _entity("old-relation-target"),
        status=MemoryStatus.RETRACTED,
        redirect_to=fact.link,
        content="Retracted because this was not an entity.",
    )
    memory.write_document(old)

    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(
            _concept("relation-source", relations=(old.link,)),
        )


def test_memory_backlinks_combine_real_edges_and_preserve_workspace_source_day(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    target = _concept("storage")
    memory.write_document(target)
    source = replace(
        _concept("source", relations=(target.link,)),
        content="[storage][s]\n\n[s]: storage.md\n\n[report](workspace:report.md)",
    )
    memory.write_document(source)
    memory.write_document(
        replace(_concept("similar"), content="storage durable concept")
    )
    refs = ReferenceResolver()
    refs.bind(
        {
            "memory": memory.canonical_reference,
            "workspace": lambda resource, fragment, day: ResourceTarget(
                resource, fragment, day or NEXT_DAY.value
            ),
        }
    )
    corpus = memory.search_corpus(
        BacklinkSearch(str(target.link), SearchOptions("all")), references=refs
    )
    assert [item.ref for item in corpus.candidates] == [str(source.link)]
    assert {e.relation for e in corpus.candidates[0].evidence} == {
        "memory_reference",
        "markdown_link",
    }
    # Historical Memory never points to today's resource merely because its name matches.
    assert (
        memory.search_corpus(
            BacklinkSearch("workspace:report.md", SearchOptions("all")), references=refs
        ).candidates
        == ()
    )
    direct = memory.inspect(str(source.link), view="direct_refs")
    assert direct["items"] == [
        {"ref": str(target.link)},
        {"ref": "workspace:report.md"},
    ]
    assert memory.inspect(str(target.link))["ref"] == str(target.link)
    with pytest.raises(SearchFailure):
        memory.inspect(str(source.link), view="backlinks")


def _memory(
    tmp_path: Path,
    *,
    session_root: Path | None = None,
) -> MemoryEngine:
    return MemoryEngine(
        settings=MemorySettings(root=tmp_path / "memory"),
        active_session_root=session_root,
    )


def _daily(day: date) -> DailyMemoryDocument:
    return DailyMemoryDocument(
        day=day,
        created_on=day,
        updated_on=day,
        content="## Events\n\nDaily evidence.",
    )


def _entity(cite: str, *, content: str = "A known entity.") -> EntityMemoryDocument:
    return EntityMemoryDocument(
        cite=cite,
        status=MemoryStatus.ACTIVE,
        created_on=DAY.value,
        updated_on=DAY.value,
        content=content,
    )


def _concept(
    cite: str,
    *,
    relations: tuple[MemoryLink, ...] = (),
) -> ConceptMemoryDocument:
    return ConceptMemoryDocument(
        cite=cite,
        status=MemoryStatus.ACTIVE,
        created_on=DAY.value,
        updated_on=DAY.value,
        content="A durable concept.",
        relations=relations,
    )


def _fact(
    cite: str,
    summary: str,
    *,
    relations: tuple[MemoryLink, ...],
    evidence: tuple[MemoryLink, ...],
) -> FactMemoryDocument:
    return FactMemoryDocument(
        cite=cite,
        status=MemoryStatus.ACTIVE,
        created_on=DAY.value,
        updated_on=DAY.value,
        content=summary,
        summary=summary,
        confidence=MemoryConfidence.HIGH,
        relations=relations,
        evidence=evidence,
    )


def _note(
    cite: str,
    title: str,
    *,
    relations: tuple[MemoryLink, ...],
    evidence: tuple[MemoryLink, ...],
) -> NoteMemoryDocument:
    return NoteMemoryDocument(
        cite=cite,
        status=MemoryStatus.ACTIVE,
        created_on=DAY.value,
        updated_on=DAY.value,
        content="A complete note that develops one durable idea.",
        title=title,
        relations=relations,
        evidence=evidence,
    )
