from __future__ import annotations

import pytest

from tinysoul.action import ActionCatalogLoader, builtin_action_catalog_root
from tinysoul.action.config import (
    LLMActionProfileResolver,
    parse_action_settings,
    validate_llm_action_routes,
)
from tinysoul.infra.config import ConfigError


def _package_catalog():
    with builtin_action_catalog_root() as root:
        return ActionCatalogLoader().load(root)


def test_llm_action_profile_resolver_uses_override_then_default() -> None:
    settings = parse_action_settings(
        {
            "llm_action": {
                "timeout_seconds": 30,
                "default_task_profile": "llm_action",
                "overrides": [
                    {
                        "action_id": "workspace.analyze",
                        "task_profile": "workspace_analysis",
                    }
                ],
            }
        }
    )
    resolver = LLMActionProfileResolver(settings.llm_action)

    assert resolver.profile_for("workspace.analyze") == "workspace_analysis"
    assert resolver.profile_for("workspace.describe") == "llm_action"


def test_action_settings_reject_duplicate_override_actions() -> None:
    with pytest.raises(ConfigError) as raised:
        parse_action_settings(
            {
                "llm_action": {
                    "overrides": [
                        {
                            "action_id": "workspace.analyze",
                            "task_profile": "llm_action",
                        },
                        {
                            "action_id": "workspace.analyze",
                            "task_profile": "alternate",
                        },
                    ]
                }
            }
        )

    assert raised.value.key == "action.llm_action.overrides"


@pytest.mark.parametrize(
    ("action_id", "task_profile", "expected_key"),
    (
        (
            "workspace.missing",
            "llm_action",
            "action.llm_action.overrides.0.action_id",
        ),
        (
            "workspace.read",
            "llm_action",
            "action.llm_action.overrides.0.action_id",
        ),
        (
            "workspace.analyze",
            "missing_profile",
            "action.llm_action.overrides.0.task_profile",
        ),
    ),
)
def test_llm_action_route_validation_rejects_invalid_cross_module_reference(
    action_id: str,
    task_profile: str,
    expected_key: str,
) -> None:
    settings = parse_action_settings(
        {
            "llm_action": {
                "default_task_profile": "llm_action",
                "overrides": [
                    {"action_id": action_id, "task_profile": task_profile}
                ],
            }
        }
    )

    with pytest.raises(ConfigError) as raised:
        validate_llm_action_routes(
            settings.llm_action,
            catalog=_package_catalog(),
            task_profiles=("llm_action", "workspace_analysis"),
        )

    assert raised.value.key == expected_key


def test_llm_action_route_validation_accepts_current_catalog_llm_action() -> None:
    settings = parse_action_settings(
        {
            "llm_action": {
                "default_task_profile": "llm_action",
                "overrides": [
                    {
                        "action_id": "workspace.analyze",
                        "task_profile": "workspace_analysis",
                    }
                ],
            }
        }
    )

    validate_llm_action_routes(
        settings.llm_action,
        catalog=_package_catalog(),
        task_profiles=("llm_action", "workspace_analysis"),
    )
