from tinysoul.kernel.action import ActionResult
from tests.support.catalog import builtin_action_catalog_root
from tinysoul.kernel.action.catalog.loader import ActionCatalogLoader
from tinysoul.kernel.loop.lifecycle.completion import AnswerCompletionDetector


def test_user_catalog_excludes_reflection_write_domains() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    domains = {domain.name for domain in catalog.domains()}
    assert "core" in domains
    assert "memory" in domains
    assert catalog.has_action("core.answer")


def test_reflection_actions_share_owner_domains_and_scenario_visibility() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    assert catalog.get_action("home.diff").visibility.for_scenario("home_reflection")
    assert catalog.get_action("memory.write").visibility.for_scenario(
        "memory_reflection"
    )
    assert not catalog.get_action("home.diff").visibility.for_scenario("user")


def test_core_completion_intent_is_shared_by_profiles() -> None:
    result = ActionResult.success(
        call_id="call",
        invoke_id="invoke",
        batch_id="batch",
        action_name="core.answer",
        sequence=1,
        domain="core",
        payload={"text": "Reviewed the accepted changes."},
    )
    completion = AnswerCompletionDetector().detect((result,))
    assert completion is not None
    assert completion["kind"] == "answer"
    assert completion["text"] == result.payload["text"]
