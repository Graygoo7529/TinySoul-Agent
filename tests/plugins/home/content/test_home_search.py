from __future__ import annotations

from pathlib import Path
from datetime import date

import pytest

from tinysoul.infra.references import ReferenceResolver, ResourceTarget
from tinysoul.kernel.retrieval.contracts import (
    QueryDiscovery,
    SeedRefinement,
    BacklinkSearch,
    SearchOptions,
    SearchMode,
    SearchSemantic,
    TextQuery,
    CandidateSource,
    SearchFailure,
)
from tinysoul.kernel.retrieval.engine import SearchEngine, SearchViews
from tinysoul.kernel.retrieval.policy import SearchPolicy
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings


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
    request = QueryDiscovery(TextQuery("zephyr"), SearchOptions("all"))
    corpus = owner.search_corpus(request, references=refs)
    page = await SearchEngine(views=SearchViews()).search(
        request,
        policy=SearchPolicy(
            "home.search", SearchMode.QUERY_DISCOVERY, (CandidateSource.LEXICAL,)
        ),
        candidates=corpus.candidates,
        query=corpus.query,
    )
    assert {item.ref for item in page.items} == {
        "home:skills@design",
        "home:skills/shared/notes.md",
    }
    skill = next(item for item in page.items if item.ref == "home:skills@design")
    assert any(
        e.ref.startswith("home:skills/design/ref/deep.md#L") and "zephyr" in e.text
        for e in skill.evidence
    )
    assert "skills_action" not in repr(corpus)
    seeds = SeedRefinement(
        "storage",
        SearchOptions("skills", semantic=SearchSemantic.SELECT),
        ("home:skills@other",),
    )
    seeded = owner.search_corpus(seeds, references=refs)
    assert {item.ref for item in seeded.candidates} == {"home:skills@other"}


def test_backlinks_preserve_actual_source_cross_space_and_fragment(tmp_path: Path):
    owner, refs = _home(tmp_path)
    for anchor in ("memory:concept/storage", "memory:concept/storage#durability"):
        corpus = owner.search_corpus(
            BacklinkSearch(anchor, SearchOptions("all")), references=refs
        )
        assert [item.ref for item in corpus.candidates] == [
            "home:skills/design/ref/deep.md"
        ]
        assert corpus.candidates[0].attributes["top_ref"] == "home:skills@design"
    assert not owner.search_corpus(
        BacklinkSearch("memory:concept/storage#other", SearchOptions("all")),
        references=refs,
    ).candidates
    corpus = owner.search_corpus(
        BacklinkSearch("home:skills/design/ref/deep.md", SearchOptions("all")),
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
        BacklinkSearch("workspace:report.md", SearchOptions("all")), references=refs
    )
    assert [item.ref for item in corpus.candidates] == ["home:agent/AGENT.md"]
    assert days == [None, None]
