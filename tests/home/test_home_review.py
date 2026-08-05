from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.home import (
    AgentHomeContractError,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeSettings,
    HomeReviewResolution,
)


_SKILL_TEXT = """---
title: Review Skill
description: Review working guidance.
---

# Review Skill

Keep the current method.
"""

_REWRITTEN_SKILL_TEXT = """---
title: Review Skill
description: Review working guidance.
---

# Review Skill

Use the revised method.
"""


def test_home_maintenance_resolves_accept_reject_and_rewrite(tmp_path: Path) -> None:
    actual = tmp_path / "home" / "agent" / "review.md"
    actual.parent.mkdir(parents=True)
    actual.write_text("old", encoding="utf-8")
    home = _home(tmp_path)

    home.write_top("home:agent@review", "runtime", overwrite=True)
    accepted = home.review_snapshot().changes[0]
    outcome = home.resolve_review(
        accepted.token,
        HomeReviewResolution.ACCEPT,
    )
    assert outcome.remaining_reviews == 0
    assert actual.read_text(encoding="utf-8") == "runtime"

    home.write_top("home:agent@review", "discard", overwrite=True)
    rejected = home.review_snapshot().changes[0]
    home.resolve_review(rejected.token, HomeReviewResolution.REJECT)
    assert actual.read_text(encoding="utf-8") == "runtime"

    home.write_top("home:agent@review", "draft", overwrite=True)
    rewritten = home.review_snapshot().changes[0]
    home.resolve_review(
        rewritten.token,
        HomeReviewResolution.REWRITE,
        rewrite_text="curated",
    )
    assert actual.read_text(encoding="utf-8") == "curated"


def test_home_maintenance_rejects_stale_change_token(tmp_path: Path) -> None:
    actual = tmp_path / "home" / "agent" / "review.md"
    actual.parent.mkdir(parents=True)
    actual.write_text("old", encoding="utf-8")
    home = _home(tmp_path)
    home.write_top("home:agent@review", "first", overwrite=True)
    stale = home.review_snapshot().changes[0]
    home.write_top("home:agent@review", "second", overwrite=True)

    with pytest.raises(AgentHomeInvariantError, match="stale or unknown"):
        home.resolve_review(stale.token, HomeReviewResolution.ACCEPT)


def test_skill_memory_is_an_independent_skill_review_until_resolved(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(_SKILL_TEXT, encoding="utf-8")
    home = _home(tmp_path)
    home.write_resource(
        "home:skills/review/SKILL_MEMORY.md",
        "The method may need a clearer final step.",
    )

    first = home.review_snapshot()
    second = home.review_snapshot()

    assert first.changes == ()
    assert len(first.skill_reviews) == 1
    assert second.skill_reviews[0].token == first.skill_reviews[0].token
    assert home.review_pending().skill_memory_count == 1
    assert (
        tmp_path / "runtime" / "home" / "skills" / "review" / "SKILL_MEMORY.md"
    ).exists()

    review = second.skill_reviews[0]
    outcome = home.resolve_review(
        review.token,
        HomeReviewResolution.REJECT,
    )

    assert outcome.remaining_reviews == 0
    assert skill.read_text(encoding="utf-8") == _SKILL_TEXT
    assert home.review_pending().pending is False


def test_skill_memory_review_can_rewrite_actual_skill_but_cannot_accept(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(_SKILL_TEXT, encoding="utf-8")
    home = _home(tmp_path)
    home.write_resource(
        "home:skills/review/SKILL_MEMORY.md",
        "Use the revised method.",
    )
    review = home.review_snapshot().skill_reviews[0]

    with pytest.raises(AgentHomeContractError, match="does not have a runtime"):
        home.resolve_review(
            review.token,
            HomeReviewResolution.ACCEPT,
        )

    assert home.review_pending().skill_memory_count == 1
    review = home.review_snapshot().skill_reviews[0]
    outcome = home.resolve_review(
        review.token,
        HomeReviewResolution.REWRITE,
        rewrite_text=_REWRITTEN_SKILL_TEXT,
    )

    assert outcome.remaining_reviews == 0
    assert skill.read_text(encoding="utf-8") == _REWRITTEN_SKILL_TEXT


def test_skill_memory_invalid_rewrite_preserves_actual_and_review(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(_SKILL_TEXT, encoding="utf-8")
    home = _home(tmp_path)
    home.write_resource(
        "home:skills/review/SKILL_MEMORY.md",
        "The frontmatter should remain valid.",
    )
    review = home.review_snapshot().skill_reviews[0]

    with pytest.raises(AgentHomeContractError, match="frontmatter"):
        home.resolve_review(
            review.token,
            HomeReviewResolution.REWRITE,
            rewrite_text="invalid skill",
        )

    assert skill.read_text(encoding="utf-8") == _SKILL_TEXT
    assert home.review_pending().skill_memory_count == 1


def test_home_maintenance_finalize_requires_all_diffs_and_removes_runtime(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    home.write_top("home:agent@new", "new fact", overwrite=False)

    with pytest.raises(AgentHomeContractError, match="differences remain"):
        home.remove_resolved_overlay()

    change = home.review_snapshot().changes[0]
    home.resolve_review(change.token, HomeReviewResolution.ACCEPT)
    assert home.remove_resolved_overlay() is True
    assert not home.runtime_root.exists()


def test_home_maintenance_next_access_recreates_runtime_overlay(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert home.remove_resolved_overlay() is True
    assert not home.runtime_root.exists()

    home.write_top("home:agent@next", "next fact", overwrite=False)

    assert home.runtime_root.exists()
    assert home.review_pending().change_count == 1


def test_home_maintenance_does_not_remove_unowned_runtime_metadata(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    marker = home.runtime_root / ".tinysoul" / "unowned.json"
    marker.write_text("{}", encoding="utf-8")

    with pytest.raises(AgentHomeInvariantError, match="unowned metadata"):
        home.remove_resolved_overlay()

    assert marker.exists()
    assert (home.runtime_root / ".tinysoul" / "home_overlay.json").exists()


def test_home_maintenance_restores_runtime_root_when_final_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _home(tmp_path)

    def fail_remove(path: Path) -> None:
        raise OSError(f"cannot remove {path.name}")

    monkeypatch.setattr("tinysoul.home.overlay.shutil.rmtree", fail_remove)

    with pytest.raises(AgentHomeIOError, match="Failed to remove empty runtime Home"):
        home.remove_resolved_overlay()

    assert home.runtime_root.exists()
    assert (home.runtime_root / ".tinysoul" / "home_overlay.json").exists()


def _home(root: Path) -> AgentHomeEngine:
    original = root / "home"
    original.mkdir(parents=True, exist_ok=True)
    return AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=root / "runtime" / "home",
        )
    ).build()
