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
    HomeMaintenanceResolution,
)


def test_home_maintenance_resolves_accept_reject_and_rewrite(tmp_path: Path) -> None:
    actual = tmp_path / "home" / "why" / "review.md"
    actual.parent.mkdir(parents=True)
    actual.write_text("old", encoding="utf-8")
    home = _home(tmp_path)

    home.write_top("home:why@review", "runtime", overwrite=True)
    accepted = home.maintenance_snapshot().changes[0]
    outcome = home.resolve_maintenance(
        accepted.token,
        HomeMaintenanceResolution.ACCEPT,
    )
    assert outcome.remaining_changes == 0
    assert actual.read_text(encoding="utf-8") == "runtime"

    home.write_top("home:why@review", "discard", overwrite=True)
    rejected = home.maintenance_snapshot().changes[0]
    home.resolve_maintenance(rejected.token, HomeMaintenanceResolution.REJECT)
    assert actual.read_text(encoding="utf-8") == "runtime"

    home.write_top("home:why@review", "draft", overwrite=True)
    rewritten = home.maintenance_snapshot().changes[0]
    home.resolve_maintenance(
        rewritten.token,
        HomeMaintenanceResolution.REWRITE,
        rewrite_text="curated",
    )
    assert actual.read_text(encoding="utf-8") == "curated"


def test_home_maintenance_rejects_stale_change_token(tmp_path: Path) -> None:
    actual = tmp_path / "home" / "why" / "review.md"
    actual.parent.mkdir(parents=True)
    actual.write_text("old", encoding="utf-8")
    home = _home(tmp_path)
    home.write_top("home:why@review", "first", overwrite=True)
    stale = home.maintenance_snapshot().changes[0]
    home.write_top("home:why@review", "second", overwrite=True)

    with pytest.raises(AgentHomeInvariantError, match="stale or unknown"):
        home.resolve_maintenance(stale.token, HomeMaintenanceResolution.ACCEPT)


def test_home_maintenance_finalize_requires_all_diffs_and_removes_runtime(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    home.write_top("home:why@new", "new fact", overwrite=False)

    with pytest.raises(AgentHomeContractError, match="differences remain"):
        home.finalize_maintenance()

    change = home.maintenance_snapshot().changes[0]
    home.resolve_maintenance(change.token, HomeMaintenanceResolution.ACCEPT)
    assert home.finalize_maintenance() is True
    assert not home.runtime_root.exists()


def test_home_maintenance_next_access_recreates_runtime_overlay(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert home.finalize_maintenance() is True
    assert not home.runtime_root.exists()

    home.write_top("home:why@next", "next fact", overwrite=False)

    assert home.runtime_root.exists()
    assert home.maintenance_pending().change_count == 1


def test_home_maintenance_does_not_remove_unowned_runtime_metadata(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    marker = home.runtime_root / ".tinysoul" / "unowned.json"
    marker.write_text("{}", encoding="utf-8")

    with pytest.raises(AgentHomeInvariantError, match="unowned metadata"):
        home.finalize_maintenance()

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
        home.finalize_maintenance()

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
