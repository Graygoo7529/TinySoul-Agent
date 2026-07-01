from __future__ import annotations

from pathlib import Path

from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.specs import ActionParallelPolicy


def test_load_builtin_catalog() -> None:
    root = Path("tinysoul/action/builtin")

    catalog = ActionCatalogLoader().load(root)

    assert catalog.has_domain("core")
    assert catalog.has_domain("workspace")
    answer = catalog.get_action("core.answer")
    assert answer.domain == "core"
    assert answer.tool.schema["type"] == "object"
    assert answer.runtime.timeout_seconds == 10.0
    assert answer.runtime.parallel_policy is ActionParallelPolicy.SERIAL


def test_catalog_view_by_domain() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    view = catalog.with_domains(("workspace",))

    assert [domain.name for domain in view.domains()] == ["workspace"]
    assert [action.name for action in view.actions()] == ["workspace.scan"]
