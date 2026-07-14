from __future__ import annotations

import json
from pathlib import Path

import pytest

from tinysoul.home import (
    AgentHomeContractError,
    AgentHomeEngine,
    AgentHomeEngineBuilder,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeRuntimeCopyRequired,
    AgentHomeSettings,
    HomeOverlayState,
)
from tinysoul.home.overlay import HomeOverlayManager


def test_legacy_home_memory_path_and_link_are_rejected(tmp_path: Path) -> None:
    memory = tmp_path / "home" / "memory" / "2026" / "07" / "2026-07-11.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("old memory", encoding="utf-8")
    with pytest.raises(AgentHomeInvariantError, match="cannot exist inside Agent Home"):
        _home(tmp_path)

    memory.unlink()
    home = _home(tmp_path)
    with pytest.raises(AgentHomeContractError, match="Unsupported Home"):
        home.parse_link("home:memory@2026-07-11")
    with pytest.raises(AgentHomeContractError, match="Unsupported Home"):
        home.read_resource("home:memory/2026/07/2026-07-11.md")


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


def test_runtime_only_top_is_catalogued_across_restart_and_tombstone_hides_it(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)

    created = home.write_top(
        "home:what@tiny_soul",
        "runtime entity",
        what_kind="entity",
    )

    assert created.state is HomeOverlayState.CREATED
    assert "home:what@tiny_soul" in home.loadable_background_links()
    assert home.read_top("home:what@tiny_soul") == "runtime entity"
    assert not (
        tmp_path / "home" / "what" / "entity" / "tiny_soul.md"
    ).exists()

    restarted = _home(tmp_path)
    assert "home:what@tiny_soul" in restarted.loadable_background_links()
    deleted = restarted.delete_top("home:what@tiny_soul")

    assert deleted.state is HomeOverlayState.DELETED
    assert "home:what@tiny_soul" not in restarted.loadable_background_links()
    with pytest.raises(AgentHomeContractError, match="does not exist"):
        restarted.read_top("home:what@tiny_soul")


def test_top_tombstone_hides_actual_without_modifying_it(tmp_path: Path) -> None:
    source = tmp_path / "home" / "why" / "obsolete.md"
    source.parent.mkdir(parents=True)
    source.write_text("actual reason", encoding="utf-8")
    home = _home(tmp_path)

    deleted = home.delete_top("home:why@obsolete")

    assert deleted.state is HomeOverlayState.DELETED
    assert source.read_text(encoding="utf-8") == "actual reason"
    assert "home:why@obsolete" not in home.loadable_background_links()


def test_materialized_top_remains_effective_when_actual_changes_externally(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "why" / "stable.md"
    source.parent.mkdir(parents=True)
    source.write_text("baseline", encoding="utf-8")
    home = _home(tmp_path)
    link = home.parse_link("home:why@stable")
    assert home.ensure_runtime_copy(link) is True

    source.write_text("external change", encoding="utf-8")

    assert home.read_top("home:why@stable") == "baseline"
    assert "home:why@stable" in home.loadable_background_links()


def test_top_mutation_enforces_what_classification_core_and_link_rules(
    tmp_path: Path,
) -> None:
    core = tmp_path / "home" / "agent" / "AGENT.md"
    core.parent.mkdir(parents=True)
    core.write_text("core before", encoding="utf-8")
    home = _home(tmp_path)

    with pytest.raises(AgentHomeContractError, match="requires entity or concept"):
        home.write_top("home:what@missing_kind", "value")
    with pytest.raises(AgentHomeContractError, match="entity or concept"):
        home.write_top(
            "home:what@invalid_kind",
            "value",
            what_kind="event",
        )

    patched = home.patch_top(
        "home:agent@core",
        old_text="core before",
        new_text="core after",
    )
    assert patched.state is HomeOverlayState.MODIFIED
    assert home.read_top("home:agent@core") == "core after"
    assert core.read_text(encoding="utf-8") == "core before"
    with pytest.raises(AgentHomeContractError, match="cannot be deleted"):
        home.delete_top("home:agent@core")
    with pytest.raises(AgentHomeContractError, match="Unsupported Home"):
        home.write_top("home:memory@2026-07-11", "changed", overwrite=True)


def test_duplicate_effective_what_classifications_are_rejected(tmp_path: Path) -> None:
    entity = tmp_path / "home" / "what" / "entity" / "duplicate.md"
    concept = tmp_path / "home" / "what" / "concept" / "duplicate.md"
    entity.parent.mkdir(parents=True)
    concept.parent.mkdir(parents=True)
    entity.write_text("entity", encoding="utf-8")
    concept.write_text("concept", encoding="utf-8")
    home = _home(tmp_path)

    with pytest.raises(AgentHomeInvariantError, match="multiple effective files"):
        home.loadable_background_links()


def test_prompt_mounts_follow_action_catalog_and_mutate_only_runtime(
    tmp_path: Path,
) -> None:
    actual = tmp_path / "home" / "how_domain" / "workspace" / "DOMAIN.md"
    actual.parent.mkdir(parents=True)
    actual.write_text("actual guidance", encoding="utf-8")
    home = _home(tmp_path)
    home.reconcile_prompt_mounts(
        domains=("workspace",),
        actions=(("workspace", "workspace.rewrite"),),
    )
    assert home.ensure_runtime_copy(
        home.parse_link("home:how_domain:workspace")
    ) is True

    assert home.guidance_for_action("workspace", "workspace.rewrite") is None
    written = home.write_prompt_mount(
        "home:how_action:workspace/rewrite",
        "runtime action guidance",
    )
    patched = home.patch_prompt_mount(
        "home:how_action:workspace/rewrite",
        old_text="runtime action",
        new_text="updated action",
    )

    assert written.state is HomeOverlayState.CREATED
    assert patched.state is HomeOverlayState.CREATED
    assert home.guidance_for_action("workspace", "workspace.rewrite") == (
        "updated action guidance"
    )
    assert home.guidance_for_domain("workspace") == "actual guidance"
    assert actual.read_text(encoding="utf-8") == "actual guidance"
    with pytest.raises(AgentHomeContractError, match="not defined"):
        home.write_prompt_mount("home:how_domain:session", "invalid")

    home.reconcile_prompt_mounts(domains=(), actions=())
    assert actual.read_text(encoding="utf-8") == "actual guidance"
    with pytest.raises(AgentHomeContractError, match="not defined"):
        home.guidance_for_domain("workspace")

    home.reconcile_prompt_mounts(
        domains=("workspace",),
        actions=(("workspace", "workspace.rewrite"),),
    )
    assert home.guidance_for_domain("workspace") == "actual guidance"


def test_skill_memory_exists_only_in_general_how_runtime_package(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "home" / "how" / "refactor" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill", encoding="utf-8")
    home = _home(tmp_path)

    created = home.write_resource(
        "home:how/refactor/SKILL_MEMORY.md",
        "temporary feedback",
    )

    assert created.state is HomeOverlayState.CREATED
    assert home.read_resource("home:how/refactor/SKILL_MEMORY.md").text == (
        "temporary feedback"
    )
    assert not (skill.parent / "SKILL_MEMORY.md").exists()
    restarted = _home(tmp_path)
    assert restarted.read_resource("home:how/refactor/SKILL_MEMORY.md").text == (
        "temporary feedback"
    )

    for link in (
        "home:how/missing/SKILL_MEMORY.md",
        "home:how/refactor/DOMAIN_MEMORY.md",
        "home:why/SKILL_MEMORY.md",
    ):
        with pytest.raises(AgentHomeContractError):
            home.write_resource(link, "invalid")


def test_actual_home_rejects_runtime_only_skill_memory(tmp_path: Path) -> None:
    invalid = tmp_path / "home" / "how" / "refactor" / "SKILL_MEMORY.md"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("invalid actual memory", encoding="utf-8")

    with pytest.raises(AgentHomeInvariantError, match="actual Home"):
        _home(tmp_path)


def test_runtime_home_rejects_memory_overlay_content(tmp_path: Path) -> None:
    original = tmp_path / "home"
    original.mkdir()
    invalid = (
        tmp_path
        / "runtime"
        / "home"
        / "memory"
        / "2026"
        / "07"
        / "2026-07-11.md"
    )
    invalid.parent.mkdir(parents=True)
    invalid.write_text("invalid runtime memory", encoding="utf-8")

    with pytest.raises(AgentHomeInvariantError, match="runtime overlay"):
        _home(tmp_path)


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
