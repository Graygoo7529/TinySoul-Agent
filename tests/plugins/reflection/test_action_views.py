from tinysoul.kernel.action import (ActionResult)
from tinysoul.agent.catalog import builtin_action_catalog_root
from tinysoul.kernel.action.core.loader import ActionCatalogLoader
from tinysoul.kernel.loop.completion import AnswerCompletionDetector
from tinysoul.plugins.reflection.resources import maintenance_action_catalog_root


def test_user_catalog_excludes_reflection_write_domains() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    domains = {domain.name for domain in catalog.domains()}
    assert "core" in domains
    assert not domains.intersection({"home_reflection", "memory_reflection"})
    assert catalog.has_action("core.answer")


def test_reflection_package_contains_only_independent_owner_write_domains() -> None:
    with maintenance_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    assert {action.name for action in catalog.actions()} == {
        "home_reflection.diff", "home_reflection.review",
        "memory_reflection.write_daily", "memory_reflection.write",
    }
    assert all(action.runtime.enabled for action in catalog.actions())


def test_core_completion_intent_is_shared_by_profiles() -> None:
    result = ActionResult.success(
        call_id="call", invoke_id="invoke", batch_id="batch",
        action_name="core.answer", sequence=1, domain="core",
        payload={"text": "Reviewed the accepted changes."},
    )
    completion = AnswerCompletionDetector().detect((result,))
    assert completion is not None
    assert completion["kind"] == "answer"
    assert completion["text"] == result.payload["text"]
