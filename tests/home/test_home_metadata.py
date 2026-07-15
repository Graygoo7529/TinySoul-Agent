from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tinysoul.home import (
    AgentHomeContractError,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeSettings,
    HomeBackgroundEntryProvider,
    HomeTopLink,
    parse_home_skill_metadata,
)
from tinysoul.home.metadata import SKILL_FRONTMATTER_MAX_CHARS


def test_skill_frontmatter_parses_exact_discovery_fields() -> None:
    metadata = parse_home_skill_metadata(
        _skill("Review Home", "Review pending Home changes."),
        link=HomeTopLink("how", "review"),
    )

    assert str(metadata.link) == "home:how@review"
    assert metadata.title == "Review Home"
    assert metadata.description == "Review pending Home changes."


@pytest.mark.parametrize(
    "text, problem",
    (
        ("# Missing\n", "must start"),
        ("---\ntitle: Missing close\n", "not closed"),
        (
            "---\ntitle: Review\ndescription: Useful\nextra: no\n---\n",
            "exactly title and description",
        ),
        ("---\ntitle: ''\ndescription: Useful\n---\n", "title must be non-empty"),
        (
            "---\ntitle: Review\ndescription: |\n  first\n  second\n---\n",
            "description must be one line",
        ),
        (
            "---\n"
            + ("x" * SKILL_FRONTMATTER_MAX_CHARS)
            + "\n---\n",
            "frontmatter exceeds",
        ),
    ),
)
def test_skill_frontmatter_rejects_ambiguous_metadata(
    text: str,
    problem: str,
) -> None:
    with pytest.raises(AgentHomeContractError, match=problem):
        parse_home_skill_metadata(text, link=HomeTopLink("how", "review"))


def test_home_builder_rejects_invalid_actual_skill(tmp_path: Path) -> None:
    skill = tmp_path / "home" / "how" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Review\n", encoding="utf-8")

    with pytest.raises(AgentHomeContractError, match="must start"):
        _home(tmp_path)


def test_home_builder_reports_oversized_skill_frontmatter(tmp_path: Path) -> None:
    skill = tmp_path / "home" / "how" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\n"
        "title: Review\n"
        "description: "
        + ("x" * SKILL_FRONTMATTER_MAX_CHARS)
        + "\n---\n",
        encoding="utf-8",
    )

    with pytest.raises(AgentHomeContractError, match="frontmatter exceeds"):
        _home(tmp_path)


def test_skill_mutation_validates_before_changing_effective_home(tmp_path: Path) -> None:
    home = _home(tmp_path)
    link = "home:how@review"
    original = _skill("Review Home", "Review pending Home changes.")
    home.write_top(link, original)

    with pytest.raises(AgentHomeContractError, match="must start"):
        home.write_top(link, "# Invalid\n", overwrite=True)
    with pytest.raises(AgentHomeContractError, match="description must be one line"):
        home.patch_top(
            link,
            old_text="description: Review pending Home changes.",
            new_text="description: |\n  first\n  second",
        )

    assert home.read_top(link) == original


def test_skill_catalog_budget_fails_without_creating_runtime_skill(
    tmp_path: Path,
) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=home_root,
            runtime_root=tmp_path / "runtime" / "home",
            skill_catalog_max_chars=40,
        )
    ).build()

    with pytest.raises(AgentHomeContractError, match="metadata catalog exceeds"):
        home.write_top("home:how@review", _skill("Review", "Review changes."))

    assert "home:how@review" not in home.loadable_background_links()


def test_home_provider_reflects_effective_skill_metadata_without_loading_body(
    tmp_path: Path,
) -> None:
    agent = tmp_path / "home" / "agent" / "AGENT.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("core", encoding="utf-8")
    skill = tmp_path / "home" / "how" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        _skill("Review Home", "Review pending Home changes."),
        encoding="utf-8",
    )
    home = _home(tmp_path)
    provider = HomeBackgroundEntryProvider(home)

    first = provider.catalog(date(2026, 7, 14))

    assert [(item.link, item.title, item.description) for item in first.items] == [
        (
            "home:how@review",
            "Review Home",
            "Review pending Home changes.",
        )
    ]
    assert not (
        tmp_path / "runtime" / "home" / "how" / "review" / "SKILL.md"
    ).exists()

    home.patch_top(
        "home:how@review",
        old_text="title: Review Home",
        new_text="title: Review Home Daily",
    )
    second = provider.catalog(date(2026, 7, 15))
    assert second.items[0].title == "Review Home Daily"

    home.delete_top("home:how@review")
    third = provider.catalog(date(2026, 7, 16))
    assert third.items == ()


def test_home_search_uses_skill_frontmatter_instead_of_body_heading(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        _skill(
            "Daily Home Review",
            "Review pending Home changes.",
            heading="Different Body Heading",
        ),
        encoding="utf-8",
    )
    home = _home(tmp_path)

    result = home.search_top("pending home changes", top_k=1)

    assert result.items[0].title == "Daily Home Review"
    assert result.items[0].summary == "Review pending Home changes."


def _home(root: Path) -> AgentHomeEngine:
    original = root / "home"
    original.mkdir(parents=True, exist_ok=True)
    return AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=root / "runtime" / "home",
        )
    ).build()


def _skill(title: str, description: str, *, heading: str = "Review") -> str:
    return (
        "---\n"
        f"title: {title}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {heading}\n"
    )
