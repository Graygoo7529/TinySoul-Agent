from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tinysoul.infra.references import ReferenceResolver, ResourceTarget
from tinysoul.kernel.retrieval.contracts import (
    BacklinksSource,
    OperationKind,
    QuerySource,
    RefsSource,
    RetrievalRequest,
    SearchFailure,
    SourceKind,
    TextQuery,
)
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.policy import RetrievalPolicy
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.home.engine import HOME_SEARCH_FILTERS


def _home(tmp_path: Path):
    root = tmp_path / "home"
    resources = {
        "agent/AGENT.md": "# Identity\ncoffee preferences\n[manual](../skills/design/ref/deep.md)",
        "skills/design/SKILL.md": "---\ntitle: Design\ndescription: Design guidance\n---\n# Design\n",
        "skills/design/ref/deep.md": "# Storage\nRare persistence detail: zephyr\n[target][m]\n\n[m]: <memory:concept/storage#durability>\n",
        "skills/shared/notes.md": "Independent shared zephyr resource",
        "skills/other/SKILL.md": "---\ntitle: Other\ndescription: Other skill\n---\n# Other\n[shared](../design/ref/deep.md)",
        "skills_action/home/search.md": "private mount zephyr",
        "agent/code.md": "```md\n[not an edge](memory:concept/storage)\n```\n`[also not](memory:concept/storage)`",
    }
    for relative, text in resources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    owner = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=root, runtime_root=tmp_path / "runtime" / "home"
        )
    ).build()
    refs = ReferenceResolver()
    refs.bind(
        {
            "home": owner.canonical_reference,
            "memory": lambda resource, fragment, day: ResourceTarget(
                resource, fragment
            ),
        }
    )
    return owner, refs


async def test_full_home_discovery_aggregates_skill_evidence_and_keeps_resources(
    tmp_path: Path,
):
    owner, refs = _home(tmp_path)
    request = RetrievalRequest(QuerySource("all", TextQuery("zephyr")))
    corpus = owner.search_corpus(request, references=refs)

    async def source(_request):
        return corpus

    page = await SearchSession(
        action_id="home.search",
        retrieval_policies=(
            RetrievalPolicy("home.search", tuple(SourceKind), tuple(OperationKind)),
        ),
        source=source,
    ).search(request)
    assert {item.ref for item in page.items} == {
        "home:skills@design",
        "home:skills/shared/notes.md",
    }
    skill = next(item for item in page.items if item.ref == "home:skills@design")
    assert any(
        e.unit.ref.startswith("home:skills/design/ref/deep.md#L") and "zephyr" in e.text
        for e in skill.fragments
    )
    assert "skills_action" not in repr(corpus)
    seeds = RetrievalRequest(RefsSource(("home:skills@other",)))
    seeded = owner.search_corpus(seeds, references=refs)
    assert {item.ref for item in seeded.candidates} == {"home:skills@other"}


def test_backlinks_preserve_actual_source_cross_space_and_fragment(tmp_path: Path):
    owner, refs = _home(tmp_path)
    for anchor in ("memory:concept/storage", "memory:concept/storage#durability"):
        corpus = owner.search_corpus(
            RetrievalRequest(BacklinksSource("all", anchor)), references=refs
        )
        assert [item.ref for item in corpus.candidates] == [
            "home:skills/design/ref/deep.md"
        ]
        assert corpus.candidates[0].attributes["top_ref"] == "home:skills@design"
    assert not owner.search_corpus(
        RetrievalRequest(BacklinksSource("all", "memory:concept/storage#other")),
        references=refs,
    ).candidates
    corpus = owner.search_corpus(
        RetrievalRequest(BacklinksSource("all", "home:skills/design/ref/deep.md")),
        references=refs,
    )
    assert {item.ref for item in corpus.candidates} == {
        "home:agent/AGENT.md",
        "home:skills/other/SKILL.md",
    }


def test_home_inspect_reads_fragments_without_model(tmp_path: Path):
    owner, _ = _home(tmp_path)
    page = owner.inspect("home:skills/design/ref/deep.md#L2")
    assert page["items"] == [
        {
            "ref": "home:skills/design/ref/deep.md#L2-L2",
            "text": "Rare persistence detail: zephyr\n",
        }
    ]
    assert owner.inspect("home:skills@design")["ref"] == "home:skills@design"
    assert owner.inspect("home:agent/AGENT.md", view="direct_refs")["items"] == [
        {"ref": "home:skills/design/ref/deep.md"}
    ]
    with pytest.raises(SearchFailure):
        owner.inspect("home:agent/AGENT.md", view="backlinks")


def test_timeless_home_links_use_workspace_owner_day(tmp_path: Path):
    owner, _ = _home(tmp_path)
    refs = ReferenceResolver()
    (tmp_path / "home/agent/AGENT.md").write_text(
        "[report](workspace:report.md)", encoding="utf-8"
    )
    days = []

    def resolve(resource, fragment, day):
        days.append(day)
        return ResourceTarget(resource, fragment, day or date(2026, 9, 25))

    refs.bind({"workspace": resolve})
    corpus = owner.search_corpus(
        RetrievalRequest(BacklinksSource("all", "workspace:report.md")), references=refs
    )
    assert [item.ref for item in corpus.candidates] == ["home:agent/AGENT.md"]
    assert days == [None, None]


async def test_home_aggregate_qualification_preserves_other_resource_content(
    tmp_path: Path,
):
    owner, refs = _home(tmp_path)
    (tmp_path / "home/skills/design/example.py").write_text(
        "print('example')", encoding="utf-8"
    )

    async def source(request):
        return owner.search_corpus(request, references=refs)

    queries = SearchSession(
        action_id="home.search",
        retrieval_policies=(
            RetrievalPolicy("home.search", tuple(SourceKind), tuple(OperationKind)),
        ),
        source=source,
        filters=HOME_SEARCH_FILTERS,
    )
    page = await queries.search(
        RetrievalRequest(
            QuerySource("skills", TextQuery("zephyr"), {"resource_types": ".py"})
        )
    )
    assert [item.ref for item in page.items] == ["home:skills@design"]
    resource_types = page.items[0].candidate.attributes["resource_types"]
    assert isinstance(resource_types, list) and set(resource_types) == {".py", ".md"}
    assert any("zephyr" in part.text for part in page.items[0].fragments)


def test_home_refs_preserve_order_ranges_and_do_not_expand_top(tmp_path: Path):
    owner, refs = _home(tmp_path)
    requested = (
        "home:skills/shared/notes.md",
        "home:skills@design#L5",
        "home:agent/AGENT.md",
        "home:skills@design#L5",
    )
    corpus = owner.search_corpus(
        RetrievalRequest(RefsSource(requested)), references=refs
    )
    assert [item.ref for item in corpus.candidates] == list(dict.fromkeys(requested))
    assert (
        "".join(unit.text for unit in corpus.candidates[1].content_units)
        == "# Design\n"
    )
    assert not any(
        "deep.md" in unit.ref
        for item in corpus.candidates
        for unit in item.content_units
    )
    top = owner.search_corpus(
        RetrievalRequest(RefsSource(("home:skills@design",))), references=refs
    )
    assert all("SKILL.md" in unit.ref for unit in top.candidates[0].content_units)


def test_home_excludes_before_consuming_source_read_budget(tmp_path: Path):
    from tinysoul.plugins.home.config import HomeSearchSettings

    root = tmp_path / "home"
    (root / "agent").mkdir(parents=True)
    (root / "agent/large.md").write_text("excluded" * 100, encoding="utf-8")
    (root / "agent/small.md").write_text("needle", encoding="utf-8")
    owner = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=root,
            runtime_root=tmp_path / "runtime/home",
            search=HomeSearchSettings(scan_limit=1, resource_max_chars=20),
        )
    ).build()
    corpus = owner.search_corpus(
        RetrievalRequest(
            QuerySource("agent", TextQuery("needle")),
            exclude_refs=("home:agent/large.md", "home:agent/missing.md"),
        ),
        references=ReferenceResolver(),
    )
    assert corpus.complete and corpus.scanned == 1
    assert [item.ref for item in corpus.candidates] == ["home:agent/small.md"]
