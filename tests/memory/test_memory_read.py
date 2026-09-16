from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra import EmbeddingBatch, EmbeddingError
from tinysoul.infra.time import BusinessDay
from tinysoul.memory import (
    ActiveMemoryBackgroundEntryProvider,
    ConceptMemoryDocument,
    DailyMemoryDocument,
    EntityMemoryDocument,
    FactMemoryDocument,
    MemoryConfidence,
    MemoryContractError,
    MemoryEngine,
    MemoryInspectRequest,
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


DAY = BusinessDay.parse("2026-07-12")
NEXT_DAY = BusinessDay.parse("2026-07-13")


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


def test_active_memory_and_non_evictable_current_latest_background(
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
    provider = ActiveMemoryBackgroundEntryProvider(memory)
    catalog = provider.catalog(NEXT_DAY.value)
    assert catalog.default_links == ("memory:current", "memory:latest")
    assert catalog.evictable_default_links == ()
    assert patched.content in provider.load("memory:current", NEXT_DAY.value)
    latest = provider.load("memory:latest", NEXT_DAY.value)
    assert "memory:daily/2026-07-12" in latest
    assert "Daily evidence" in latest


async def test_documents_inspect_backlinks_recall_and_redirects(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    daily = memory.write_document(
        _daily(DAY.value),
    )
    entity = _entity("graygoo")
    memory.write_document(entity)
    concept = _concept("agent-design", relations=(entity.link,))
    memory.write_document(concept)
    fact = _fact(
        "f-a71c9d2e5f42",
        "TinySoul uses explicit active memory.",
        relations=(concept.link,),
        evidence=(daily.link,),
    )
    memory.write_document(fact)
    note = _note(
        "n-a71c9d2e5f42",
        "Active memory design",
        relations=(entity.link, concept.link),
        evidence=(daily.link, fact.link),
    )
    memory.write_document(note)

    query = await memory.inspect(MemoryInspectRequest(query="active memory design"))
    assert {item.link for item in query.items} >= {str(note.link), str(fact.link)}

    neighborhood = await memory.inspect(MemoryInspectRequest(memory_link=concept.link))
    assert neighborhood.outgoing_count == 1
    assert neighborhood.backlink_count == 2
    assert {item.link for item in neighborhood.items} >= {
        str(entity.link),
        str(fact.link),
        str(note.link),
    }
    facts_only = await memory.inspect(
        MemoryInspectRequest(
            memory_link=concept.link,
            kinds=(MemoryKind.FACT,),
        )
    )
    assert facts_only.outgoing_count == 0
    assert facts_only.backlink_count == 1
    assert facts_only.related_count == 0
    assert [item.link for item in facts_only.items] == [str(fact.link)]

    recalled = memory.recall(note.link)
    assert recalled.metadata["title"] == "Active memory design"
    assert recalled.content.startswith("---\n")
    assert recalled.resolution_chain == (str(note.link),)

    replacement = _entity("apple")
    memory.write_document(replacement)
    stored = memory.read_document(entity.link)
    redirected = replace(
        entity,
        status=MemoryStatus.MERGED,
        redirect_to=replacement.link,
        content="Merged into memory:entity/apple.",
        updated_on=DAY.value,
    )
    memory.write_document(redirected)
    assert memory.recall(entity.link).resolution_chain == (
        "memory:entity/graygoo",
        "memory:entity/apple",
    )


def test_single_document_write_requires_existing_references(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    concept = _concept("memory-systems")
    note = _note("n-b71c9d2e5f42", "Memory systems", relations=(concept.link,), evidence=())
    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(note)
    memory.write_document(concept)
    memory.write_document(note)
    missing = _note("n-c71c9d2e5f42", "Broken note", evidence=(), relations=(
        MemoryLink.parse("memory:concept/missing"),
    ))
    with pytest.raises(MemoryContractError, match="references"):
        memory.write_document(missing)
    assert memory.recall(note.link).metadata["title"] == "Memory systems"
    assert memory.read_document(concept.link).document == concept


async def test_semantic_inspect_uses_deletable_embedding_cache(tmp_path: Path) -> None:
    client = _EmbeddingClient()
    memory = _memory(tmp_path, embedding_client=client)
    memory.write_document(_entity("semantic-target", content="Unrelated words"))
    memory.write_document(_entity("other", content="Another document"))

    result = await memory.inspect(MemoryInspectRequest(query="orbit"))
    assert result.items[0].link == "memory:entity/semantic-target"
    assert "semantic" in result.items[0].reasons
    cache = tmp_path / "memory" / ".tinysoul" / "embedding-cache.json"
    assert cache.is_file()
    assert "secret" not in cache.read_text(encoding="utf-8")


async def test_cancelled_embedding_refresh_preserves_committed_memory_and_cache(
    tmp_path: Path,
) -> None:
    class BlockingClient(_EmbeddingClient):
        def __init__(self) -> None:
            self.block = False
            self.started = asyncio.Event()
            self.closed = asyncio.Event()

        async def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
            if self.block:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.closed.set()
            return await super().embed(texts)

    client = BlockingClient()
    memory = _memory(tmp_path, embedding_client=client)
    document = _entity("semantic-target")
    memory.write_document(document)
    await memory.inspect(MemoryInspectRequest(query="orbit"))
    cache = tmp_path / "memory" / ".tinysoul" / "embedding-cache.json"
    previous_cache = cache.read_bytes()
    stored = memory.read_document(document.link)
    updated = replace(document, content="New durable knowledge.")
    client.block = True
    memory.write_document(updated)
    task = asyncio.create_task(memory.inspect(MemoryInspectRequest(query="orbit")))
    await asyncio.wait_for(client.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.closed.is_set()
    assert memory.read_document(document.link).document.content == updated.content
    assert cache.read_bytes() == previous_cache
    client.block = False
    await memory.inspect(MemoryInspectRequest(query="orbit"))
    assert cache.read_bytes() != previous_cache


async def test_embedding_failure_falls_back_to_current_lexical_facts(
    tmp_path: Path,
) -> None:
    class FailingClient(_EmbeddingClient):
        async def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
            raise EmbeddingError("Unavailable")

    memory = _memory(tmp_path, embedding_client=FailingClient())
    document = _entity("durable", content="Fresh lexical knowledge.")
    memory.write_document(document)
    result = await memory.inspect(MemoryInspectRequest(query="Fresh lexical"))
    assert result.items[0].link == str(document.link)
    assert "semantic" not in result.items[0].reasons
    assert memory.read_document(document.link).document.content == document.content


async def test_link_inspect_uses_semantic_related_with_lexical_fallback_and_kind_filter(
    tmp_path: Path,
) -> None:
    memory = MemoryEngine(
        settings=MemorySettings(root=tmp_path / "memory"),
        semantic_search=_LinkSemanticSearch(),
    )
    source = _entity("source", content="Source topic for durable memory.")
    direct = _concept("direct", relations=(source.link,))
    semantic_target = _entity("semantic-target", content="Unrelated wording.")
    lexical_target = _entity("lexical-target", content="Source topic is reused here.")
    for document in (source, direct, semantic_target, lexical_target):
        memory.write_document(document)

    result = await memory.inspect(
        MemoryInspectRequest(
            memory_link=source.link,
            kinds=(MemoryKind.ENTITY,),
            limit=4,
        )
    )

    assert result.outgoing_count == 0
    assert result.backlink_count == 0
    assert result.related_count == 2
    assert [item.link for item in result.items] == [
        str(semantic_target.link),
        str(lexical_target.link),
    ]
    assert result.items[0].reasons == ("semantic_related",)
    assert result.items[1].reasons == ("lexical_related",)
    assert all(item.kind == MemoryKind.ENTITY.value for item in result.items)


def test_memory_config_uses_current_sections_and_rejects_old_names(tmp_path: Path) -> None:
    settings = parse_memory_settings(
        {
            "root": "memory",
            "max_active_chars": 1000,
            "inspect": {"candidate_limit": 12, "default_top_k": 3, "max_top_k": 6},
            "semantic_search": {"embedding_cache_max_chars": 123456},
        },
        project_root=tmp_path,
    )
    assert settings.root == (tmp_path / "memory").resolve()
    assert settings.inspect.max_top_k == 6
    assert settings.semantic_search.embedding_cache_max_chars == 123456
    with pytest.raises(Exception):
        parse_memory_settings({"search": {}}, project_root=tmp_path)


async def test_inspect_enforces_page_budget_and_continues_without_duplicates(
    tmp_path: Path,
) -> None:
    memory = MemoryEngine(
        settings=MemorySettings(
            root=tmp_path / "memory",
            inspect=MemoryInspectSettings(
                candidate_limit=5,
                default_top_k=5,
                max_top_k=5,
                summary_max_chars=100,
                page_max_chars=650,
            ),
        )
    )
    for index in range(5):
        memory.write_document(
            _entity(f"memory-item-{index}", content="memory " + "detail " * 20),
        )

    first = await memory.inspect(MemoryInspectRequest(query="memory", limit=5))
    assert first.continuation is not None
    assert 0 < len(first.items) < 5
    second = await memory.inspect(
        MemoryInspectRequest(
            query="memory",
            limit=5,
            continuation=first.continuation,
        )
    )
    assert {item.link for item in first.items}.isdisjoint(
        item.link for item in second.items
    )
    assert len(json.dumps(first.to_json(), ensure_ascii=False, separators=(",", ":"))) <= 650
    with pytest.raises(MemoryContractError, match="stale"):
        await memory.inspect(
            MemoryInspectRequest(
                query="different query",
                limit=5,
                continuation=first.continuation,
            )
        )


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


class _EmbeddingClient:
    identity = "fake|embedding|2"
    max_batch_size = 2

    async def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        vectors = tuple(
            (1.0, 0.0)
            if text == "orbit" or "semantic-target" in text
            else (0.0, 1.0)
            for text in texts
        )
        return EmbeddingBatch(model="fake", dimensions=2, vectors=vectors)


class _LinkSemanticSearch:
    async def similarities(
        self,
        query: str,
        documents: Mapping[MemoryLink, str],
    ) -> Mapping[MemoryLink, float]:
        del query
        return {
            link: 0.95 if link.cite == "semantic-target" else 0.0
            for link in documents
        }


def _memory(
    tmp_path: Path,
    *,
    session_root: Path | None = None,
    embedding_client: _EmbeddingClient | None = None,
) -> MemoryEngine:
    return MemoryEngine(
        settings=MemorySettings(root=tmp_path / "memory"),
        active_session_root=session_root,
        embedding_client=embedding_client,
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
