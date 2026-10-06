from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.infra.references import ReferenceResolver, ResourceTarget
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.retrieval.contracts import (
    BacklinksSource,
    OperationKind,
    RefsSource,
    RetrievalRequest,
    SearchFailure,
    SourceKind,
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
    MemoryKind,
    MemoryRef,
    MemoryPatchKind,
    MemoryPatchOperation,
    MemorySettings,
    MemoryStatus,
    NoteMemoryDocument,
    parse_memory_settings,
)
from tinysoul.plugins.memory.services import MemoryService

DAY = CalendarDay.parse("2026-07-12")
NEXT_DAY = CalendarDay.parse("2026-07-13")


def test_five_kind_links_are_canonical_and_map_to_stable_paths() -> None:
    assert MemoryRef.parse("memory:daily/2026-07-12").relative_path == (
        "daily/2026/07/2026-07-12.md"
    )
    assert MemoryRef.parse("memory:entity/graygoo").relative_path == (
        "entity/graygoo.md"
    )
    assert MemoryRef.parse("memory:concept/agent-design").relative_path == (
        "concept/agent-design.md"
    )
    assert MemoryRef.parse("memory:fact/f-a71c9d2e5f42").kind is MemoryKind.FACT
    assert MemoryRef.parse("memory:note/n-a71c9d2e5f42").kind is MemoryKind.NOTE

    for invalid in (
        "memory:current",
        "memory:yesterday",
        "memory:entity/GrayGoo",
        "memory:fact/f-readable-name",
        "memory:daily/2026-7-12",
    ):
        with pytest.raises(MemoryContractError):
            MemoryRef.parse(invalid)
    with pytest.raises(MemoryContractError, match="120"):
        MemoryRef(MemoryKind.ENTITY, "a" * 121)


def test_document_dates_headings_and_redirect_kinds_are_strict() -> None:
    with pytest.raises(MemoryContractError, match="target day"):
        replace(_daily(DAY.value), updated_on=NEXT_DAY.value)
    with pytest.raises(MemoryContractError, match="level-1"):
        replace(_daily(DAY.value), content="Title\n===")
    with pytest.raises(MemoryContractError, match="same kind"):
        replace(
            _entity("old-entity"),
            status=MemoryStatus.MERGED,
            redirect_to=MemoryRef.parse("memory:concept/new-concept"),
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
    assert catalog.default_refs == ("memory:current", "memory:latest")
    assert catalog.evictable_default_refs == ()
    assert patched.content in await provider.load("memory:current", NEXT_DAY.value)
    latest = await provider.load("memory:latest", NEXT_DAY.value)
    assert "memory:daily/2026-07-12" in latest
    assert "Daily evidence" in latest


def test_single_document_write_requires_existing_references(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    concept = _concept("memory-systems")
    note = _note(
        "n-b71c9d2e5f42", "Memory systems", relations=(concept.ref,), evidence=()
    )
    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(note)
    memory.write_document(concept)
    memory.write_document(note)
    missing = _note(
        "n-c71c9d2e5f42",
        "Broken note",
        evidence=(),
        relations=(MemoryRef.parse("memory:concept/missing"),),
    )
    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(missing)
    metadata = memory.inspect(str(note.ref))["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["display"] == "Memory systems"
    assert memory.read_document(concept.ref).document == concept


def test_memory_config_uses_current_sections_and_rejects_old_names(
    tmp_path: Path,
) -> None:
    settings = parse_memory_settings(
        {
            "root": "memory",
            "max_active_chars": 1000,
            "inspect": {"page_max_chars": 4096},
            "search": {"embedding_cache_max_chars": 123456},
        },
        project_root=tmp_path,
    )
    assert settings.root == (tmp_path / "memory").resolve()
    assert settings.inspect.page_max_chars == 4096
    assert settings.search.embedding_cache_max_chars == 123456
    with pytest.raises(Exception):
        parse_memory_settings({"semantic_search": {}}, project_root=tmp_path)


def test_all_active_relation_targets_resolve_to_active_entity_or_concept(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    daily = _daily(DAY.value)
    fact = _fact(
        "f-a1b2c3d4e5f6",
        "A relation target fact.",
        relations=(),
        evidence=(daily.ref,),
    )
    memory.write_document(daily)
    memory.write_document(fact)
    old = replace(
        _entity("old-relation-target"),
        status=MemoryStatus.RETRACTED,
        redirect_to=fact.ref,
        content="Retracted because this was not an entity.",
    )
    memory.write_document(old)

    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(
            _concept("relation-source", relations=(old.ref,)),
        )


def test_memory_backlinks_combine_real_edges_and_preserve_workspace_source_day(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    target = _concept("storage")
    memory.write_document(target)
    source = replace(
        _concept("source", relations=(target.ref,)),
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
        RetrievalRequest(BacklinksSource("all", str(target.ref))), references=refs
    )
    assert [item.ref for item in corpus.candidates] == [str(source.ref)]
    assert {e.relation for e in corpus.candidates[0].evidence} == {
        "memory_reference",
        "markdown_reference",
    }
    # Historical Memory never points to today's resource merely because its name matches.
    assert (
        memory.search_corpus(
            RetrievalRequest(BacklinksSource("all", "workspace:report.md")),
            references=refs,
        ).candidates
        == ()
    )
    direct = memory.inspect(str(source.ref), view="direct_refs")
    assert direct["items"] == [
        {"ref": str(target.ref)},
        {"ref": "workspace:report.md"},
    ]
    assert memory.inspect(str(target.ref))["ref"] == str(target.ref)
    with pytest.raises(SearchFailure):
        memory.inspect(str(source.ref), view="backlinks")


def _memory(
    tmp_path: Path,
    *,
    session_root: Path | None = None,
) -> MemoryEngine:
    return MemoryEngine(
        settings=MemorySettings(root=tmp_path / "memory"),
        active_session_root=session_root,
    )


def test_memory_refs_normalize_preserve_order_and_read_the_exact_document(
    tmp_path: Path,
):
    memory = _memory(tmp_path)
    current = _concept("current")
    old = replace(
        _concept("old"),
        status=MemoryStatus.MERGED,
        redirect_to=current.ref,
        content="Moved to the current concept.",
    )
    memory.write_document(current)
    memory.write_document(old)
    corpus = memory.search_corpus(
        RetrievalRequest(
            RefsSource(
                (
                    "memory:concept/old.md",
                    str(current.ref) + "#L1",
                    str(old.ref),
                )
            )
        ),
        references=ReferenceResolver(),
    )
    assert [item.ref for item in corpus.candidates] == [
        str(old.ref),
        str(current.ref) + "#L1",
    ]
    assert "Moved to" in "".join(
        unit.text for unit in corpus.candidates[0].content_units
    )
    assert (
        "".join(unit.text for unit in corpus.candidates[1].content_units)
        == memory.read_document(current.ref).text.splitlines(keepends=True)[0]
    )


async def test_memory_date_source_and_snapshot_filter_share_one_contract(
    tmp_path: Path,
):
    from tinysoul.kernel.retrieval.contracts import DirectorySource, FilterStep
    from tinysoul.kernel.retrieval.operations import SearchSession
    from tinysoul.kernel.retrieval.policy import RetrievalPolicy
    from tinysoul.plugins.memory.engine import MEMORY_SEARCH_FILTERS

    memory = _memory(tmp_path)
    memory.write_document(_concept("older"))
    memory.write_document(replace(_concept("newer"), updated_on=NEXT_DAY.value))

    async def source(request):
        return memory.search_corpus(request, references=ReferenceResolver())

    session = SearchSession(
        action_id="memory.search",
        source=source,
        filters=MEMORY_SEARCH_FILTERS,
        retrieval_policies=(
            RetrievalPolicy("memory.search", tuple(SourceKind), tuple(OperationKind)),
        ),
    )
    where: JsonObject = {"updated_on": {"after": DAY.value.isoformat()}}
    qualified = await session.search(RetrievalRequest(DirectorySource("all", where)))
    filtered = await session.search(
        RetrievalRequest(DirectorySource("all"), (FilterStep(where),))
    )
    assert (
        [item.ref for item in qualified.items]
        == [item.ref for item in filtered.items]
        == ["memory:concept/newer"]
    )
    with pytest.raises(SearchFailure):
        await session.search(
            RetrievalRequest(
                DirectorySource("all", {"updated_on": {"after": "2026-02-30"}})
            )
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
    relations: tuple[MemoryRef, ...] = (),
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
    relations: tuple[MemoryRef, ...],
    evidence: tuple[MemoryRef, ...],
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
    relations: tuple[MemoryRef, ...],
    evidence: tuple[MemoryRef, ...],
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
