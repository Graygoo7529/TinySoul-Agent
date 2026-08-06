from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tinysoul.infra import EmbeddingBatch
from tinysoul.infra.time import BusinessDay
from tinysoul.memory import (
    ActiveMemoryBackgroundEntryProvider,
    ConceptMemoryDocument,
    DailyMemoryDocument,
    EntityMemoryDocument,
    FactMemoryDocument,
    MemoryActivity,
    MemoryConfidence,
    MemoryContractError,
    MemoryDocumentChange,
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
import tinysoul.memory.transaction as transaction_module


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
        replace(_daily(DAY.value, "0" * 64), updated_on=NEXT_DAY.value)
    with pytest.raises(MemoryContractError, match="level-1"):
        replace(_daily(DAY.value, "0" * 64), content="Title\n===")
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
    assert initial.document.revision == 0

    patched = memory.patch_active(
        day=NEXT_DAY,
        expected_digest=initial.digest,
        operations=(
            MemoryPatchOperation(
                MemoryPatchKind.APPEND,
                text="Continue memory:concept/agent-design tomorrow.",
            ),
        ),
    )
    assert patched.document.revision == 1
    assert "memory:concept/agent-design" in patched.content

    memory.write_document(_daily(DAY.value, initial.digest), expected_absent=True)
    provider = ActiveMemoryBackgroundEntryProvider(memory)
    catalog = provider.catalog(NEXT_DAY.value)
    assert catalog.default_links == ("memory:current", "memory:latest")
    assert catalog.evictable_default_links == ()
    assert patched.digest in provider.load("memory:current", NEXT_DAY.value)
    latest = provider.load("memory:latest", NEXT_DAY.value)
    assert "memory:daily/2026-07-12" in latest
    assert "Daily evidence" in latest


def test_documents_inspect_backlinks_recall_and_redirects(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    daily = memory.write_document(
        _daily(DAY.value, "0" * 64),
        expected_absent=True,
    )
    entity = _entity("graygoo")
    memory.write_document(entity, expected_absent=True)
    concept = _concept("agent-design", relations=(entity.link,))
    memory.write_document(concept, expected_absent=True)
    fact = _fact(
        "f-a71c9d2e5f42",
        "TinySoul uses explicit active memory.",
        relations=(concept.link,),
        evidence=(daily.link,),
    )
    memory.write_document(fact, expected_absent=True)
    note = _note(
        "n-a71c9d2e5f42",
        "Active memory design",
        relations=(entity.link, concept.link),
        evidence=(daily.link, fact.link),
    )
    memory.write_document(note, expected_absent=True)

    query = memory.inspect(MemoryInspectRequest(query="active memory design"))
    assert {item.link for item in query.items} >= {str(note.link), str(fact.link)}

    neighborhood = memory.inspect(MemoryInspectRequest(memory_link=concept.link))
    assert str(entity.link) in neighborhood.outgoing
    assert str(fact.link) in neighborhood.backlinks
    assert str(note.link) in neighborhood.backlinks

    recalled = memory.recall(note.link)
    assert recalled.metadata["title"] == "Active memory design"
    assert recalled.content.startswith("---\n")
    assert recalled.resolution_chain == (str(note.link),)

    replacement = _entity("apple")
    memory.write_document(replacement, expected_absent=True)
    stored = memory.read_document(entity.link)
    redirected = replace(
        entity,
        status=MemoryStatus.MERGED,
        redirect_to=replacement.link,
        content="Merged into memory:entity/apple.",
        updated_on=DAY.value,
    )
    memory.write_document(redirected, expected_digest=stored.digest)
    assert memory.recall(entity.link).resolution_chain == (
        "memory:entity/graygoo",
        "memory:entity/apple",
    )


def test_changeset_validates_cross_document_links_and_commits_atomically(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    daily = _daily(DAY.value, "1" * 64)
    memory.write_document(daily, expected_absent=True)
    concept = _concept("memory-systems")
    note = _note(
        "n-b71c9d2e5f42",
        "Memory systems",
        relations=(concept.link,),
        evidence=(daily.link,),
    )
    changeset = memory.prepare_changeset(
        target_day=DAY,
        changes=(
            MemoryDocumentChange(concept, expected_absent=True),
            MemoryDocumentChange(note, expected_absent=True),
        ),
    )
    outcome = memory.commit(changeset)
    assert outcome.changed_links == (concept.link, note.link)
    assert memory.recall(note.link).metadata["title"] == "Memory systems"

    missing = _note(
        "n-c71c9d2e5f42",
        "Broken note",
        relations=(MemoryLink.parse("memory:concept/missing"),),
        evidence=(daily.link,),
    )
    with pytest.raises(MemoryInvariantError, match="missing"):
        memory.prepare_changeset(
            target_day=DAY,
            changes=(MemoryDocumentChange(missing, expected_absent=True),),
        )


def test_semantic_inspect_uses_deletable_embedding_cache(tmp_path: Path) -> None:
    client = _EmbeddingClient()
    memory = _memory(tmp_path, embedding_client=client)
    memory.write_document(_entity("semantic-target", content="Unrelated words"), expected_absent=True)
    memory.write_document(_entity("other", content="Another document"), expected_absent=True)
    memory.refresh_embeddings()

    result = memory.inspect(MemoryInspectRequest(query="orbit"))
    assert result.items[0].link == "memory:entity/semantic-target"
    assert "semantic" in result.items[0].reasons
    cache = tmp_path / "memory" / ".tinysoul" / "embedding-cache.json"
    assert cache.is_file()
    assert "secret" not in cache.read_text(encoding="utf-8")


def test_memory_config_uses_current_sections_and_rejects_old_names(tmp_path: Path) -> None:
    settings = parse_memory_settings(
        {
            "root": "memory",
            "max_active_chars": 1000,
            "inspect": {"candidate_limit": 12, "default_top_k": 3, "max_top_k": 6},
            "daily_composition": {"chunk_max_chars": 100, "source_max_chars": 500},
        },
        project_root=tmp_path,
    )
    assert settings.root == (tmp_path / "memory").resolve()
    assert settings.inspect.max_top_k == 6
    with pytest.raises(Exception):
        parse_memory_settings({"search": {}}, project_root=tmp_path)


def test_inspect_enforces_page_budget_and_continues_without_duplicates(
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
            expected_absent=True,
        )

    first = memory.inspect(MemoryInspectRequest(query="memory", limit=5))
    assert first.continuation is not None
    assert 0 < len(first.items) < 5
    second = memory.inspect(
        MemoryInspectRequest(
            query="memory",
            limit=5,
            continuation=first.continuation,
        )
    )
    assert {item.link for item in first.items}.isdisjoint(
        item.link for item in second.items
    )


def test_transaction_rolls_forward_after_a_mid_commit_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = _memory(tmp_path)
    concept = _concept("transaction-concept")
    entity = _entity("transaction-entity")
    changeset = memory.prepare_changeset(
        target_day=DAY,
        changes=(
            MemoryDocumentChange(concept, expected_absent=True),
            MemoryDocumentChange(entity, expected_absent=True),
        ),
    )
    original_write = transaction_module.atomic_write_text
    failed = False

    def fail_second_target(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        nonlocal failed
        if path.name == "transaction-entity.md" and not failed:
            failed = True
            raise OSError("injected target failure")
        original_write(path, text, encoding=encoding)

    monkeypatch.setattr(transaction_module, "atomic_write_text", fail_second_target)
    with pytest.raises(MemoryIOError, match="transaction write failed"):
        memory.commit(changeset)
    assert (tmp_path / "memory" / "concept" / "transaction-concept.md").is_file()
    assert not (tmp_path / "memory" / "entity" / "transaction-entity.md").exists()

    monkeypatch.setattr(transaction_module, "atomic_write_text", original_write)
    memory.recover()
    assert memory.recall(concept.link).link == str(concept.link)
    assert memory.recall(entity.link).link == str(entity.link)
    assert not (tmp_path / "memory" / ".tinysoul" / "transactions").exists()


def test_transaction_prechecks_every_cas_before_writing_any_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = _memory(tmp_path)
    concept = _concept("cas-concept")
    entity = _entity("cas-entity")
    changeset = memory.prepare_changeset(
        target_day=DAY,
        changes=(
            MemoryDocumentChange(concept, expected_absent=True),
            MemoryDocumentChange(entity, expected_absent=True),
        ),
    )
    original_write = transaction_module.atomic_write_text

    def inject_conflict(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        original_write(path, text, encoding=encoding)
        if path.name == "manifest.json":
            target = tmp_path / "memory" / "entity" / "cas-entity.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("external conflict", encoding="utf-8")

    monkeypatch.setattr(transaction_module, "atomic_write_text", inject_conflict)
    with pytest.raises(MemoryInvariantError, match="absent CAS"):
        memory.commit(changeset)
    assert not (tmp_path / "memory" / "concept" / "cas-concept.md").exists()


class _EmbeddingClient:
    identity = "fake|embedding|2"
    max_batch_size = 2

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        vectors = tuple(
            (1.0, 0.0)
            if text == "orbit" or "semantic-target" in text
            else (0.0, 1.0)
            for text in texts
        )
        return EmbeddingBatch(model="fake", dimensions=2, vectors=vectors)


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


def _daily(day: date, active_digest: str) -> DailyMemoryDocument:
    return DailyMemoryDocument(
        day=day,
        revision=0,
        created_on=day,
        updated_on=day,
        session_revision=1,
        active_memory_digest=active_digest,
        content="## Events\n\nDaily evidence.",
    )


def _entity(cite: str, *, content: str = "A known entity.") -> EntityMemoryDocument:
    return EntityMemoryDocument(
        cite=cite,
        status=MemoryStatus.ACTIVE,
        created_on=DAY.value,
        updated_on=DAY.value,
        activity=MemoryActivity(DAY.value, 1),
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
        activity=MemoryActivity(DAY.value, 1),
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
        activity=MemoryActivity(DAY.value, 1),
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
        activity=MemoryActivity(DAY.value, 1),
        content="A complete note that develops one durable idea.",
        title=title,
        relations=relations,
        evidence=evidence,
    )
