from __future__ import annotations

import json
from pathlib import Path

import pytest

from tinysoul.home import (
    AgentHomeContractError,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeIOError,
    AgentHomeRuntimeCopyRequired,
    AgentHomeSettings,
    HomeOverlayState,
)
from tinysoul.home.overlay import HomeOverlayManager


def test_historical_memory_reads_original_without_runtime_copy(tmp_path: Path) -> None:
    memory = tmp_path / "home" / "memory" / "old.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("old memory", encoding="utf-8")
    home = _home(tmp_path)

    resource = home.read_resource("home:memory/old.md")
    top = home.read_top("home:memory@old")
    prepared = home.ensure_runtime_copy(home.parse_link("home:memory/old.md"))

    assert resource.text == "old memory"
    assert top == "old memory"
    assert prepared is False
    assert not (tmp_path / "runtime" / "home" / "memory" / "old.md").exists()


def test_home_overlay_mutations_survive_restart_without_touching_original(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "how" / "refactor" / "references" / "check.md"
    source.parent.mkdir(parents=True)
    source.write_text("before", encoding="utf-8")
    home = _home(tmp_path)
    link = "home:how/refactor/references/check.md"

    with pytest.raises(AgentHomeRuntimeCopyRequired):
        home.read_resource(link)
    assert home.ensure_runtime_copy(home.parse_link(link)) is True
    copied = home.read_resource(link)
    patched = home.patch_resource(
        link,
        old_text="before",
        new_text="after",
        expected_digest=copied.digest,
    )
    created = home.write_resource(
        "home:how/refactor/references/new.md",
        "new resource",
    )

    assert patched.state is HomeOverlayState.MODIFIED
    assert created.state is HomeOverlayState.CREATED
    assert source.read_text(encoding="utf-8") == "before"

    restarted = _home(tmp_path)
    assert restarted.read_resource(link).text == "after"
    assert restarted.read_resource(
        "home:how/refactor/references/new.md"
    ).text == "new resource"

    deleted = restarted.delete_resource(
        link,
        expected_digest=restarted.read_resource(link).digest,
    )
    assert deleted.state is HomeOverlayState.DELETED
    with pytest.raises(AgentHomeContractError, match="deleted"):
        restarted.read_resource(link)
    assert source.read_text(encoding="utf-8") == "before"

    manifest = json.loads(
        (
            tmp_path
            / "runtime"
            / "home"
            / ".tinysoul"
            / "home_overlay.json"
        ).read_text(encoding="utf-8")
    )
    records = {item["relative_path"]: item for item in manifest["records"]}
    assert records["how/refactor/references/check.md"]["state"] == "deleted"
    assert records["how/refactor/references/new.md"]["mtime_ns"] > 0


def test_home_builder_migrates_day_bound_manifest_to_cross_day_schema(
    tmp_path: Path,
) -> None:
    original = tmp_path / "home"
    original.mkdir()
    manifest_path = (
        tmp_path / "runtime" / "home" / ".tinysoul" / "home_overlay.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "day": "2026-07-12",
                "revision": 4,
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()

    migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert migrated == {
        "records": [],
        "revision": 4,
        "schema_version": 2,
    }


@pytest.mark.parametrize(
    "link",
    (
        "home:what/entity.md",
        "home:why/QA_rule.md",
        "home:how/refactor/SKILL.md",
        "home:memory/old.md",
    ),
)
def test_home_overlay_rejects_top_level_and_memory_mutation(
    tmp_path: Path,
    link: str,
) -> None:
    home = _home(tmp_path)

    with pytest.raises(AgentHomeContractError):
        home.write_resource(link, "not allowed")


def test_home_operation_recovers_file_replaced_before_manifest_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "home"
    original.mkdir()
    runtime = tmp_path / "runtime" / "home"
    manager = HomeOverlayManager(original_root=original, runtime_root=runtime)
    manager.initialize()
    original_save = manager._store.save
    failed = False

    def fail_once(manifest) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise AgentHomeIOError("injected manifest failure")
        original_save(manifest)

    monkeypatch.setattr(manager._store, "save", fail_once)

    with pytest.raises(AgentHomeIOError, match="injected"):
        manager.write(
            "how/refactor/references/recovered.md",
            "recover me",
            overwrite=False,
            expected_digest="",
        )

    target = runtime / "how" / "refactor" / "references" / "recovered.md"
    assert target.read_text(encoding="utf-8") == "recover me"
    assert tuple((runtime / ".tinysoul" / "operations").iterdir())

    recovered = HomeOverlayManager(original_root=original, runtime_root=runtime)
    manifest = recovered.initialize()
    effective = recovered.effective("how/refactor/references/recovered.md")

    assert effective is not None
    assert effective.state is HomeOverlayState.CREATED
    assert manifest.records[0].mtime_ns > 0
    assert not tuple((runtime / ".tinysoul" / "operations").iterdir())


def test_home_patch_enforces_complete_resource_write_limit(tmp_path: Path) -> None:
    original = tmp_path / "home"
    original.mkdir()
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=tmp_path / "runtime" / "home",
            max_write_chars=8,
        )
    ).build()
    link = "home:how/refactor/references/limited.md"
    home.write_resource(link, "before")

    with pytest.raises(AgentHomeContractError, match="exceeds"):
        home.patch_resource(
            link,
            old_text="before",
            new_text="much too long",
        )

    assert home.read_resource(link).text == "before"


def _home(root: Path) -> AgentHomeEngine:
    original = root / "home"
    original.mkdir(parents=True, exist_ok=True)
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=original,
            runtime_root=root / "runtime" / "home",
        )
    ).build()
    return home
