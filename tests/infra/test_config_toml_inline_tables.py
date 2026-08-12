from __future__ import annotations

from pathlib import Path

from tinysoul.infra.config import ConfigFileToml


def test_config_toml_round_trips_inline_table_arrays(tmp_path: Path) -> None:
    path = tmp_path / "action.toml"
    document = ConfigFileToml(path)
    document.set_value(
        "action.llm_action.overrides",
        [
            {
                "action_id": "workspace.analyze",
                "task_profile": "workspace_analysis",
            },
            {
                "action_id": "workspace.describe",
                "task_profile": "llm_action",
            },
        ],
    )
    document.save()

    loaded = ConfigFileToml(path)

    assert loaded.data["action"] == {
        "llm_action": {
            "overrides": [
                {
                    "action_id": "workspace.analyze",
                    "task_profile": "workspace_analysis",
                },
                {
                    "action_id": "workspace.describe",
                    "task_profile": "llm_action",
                },
            ]
        }
    }
    text = path.read_text(encoding="utf-8")
    assert '{ action_id = "workspace.analyze", task_profile = "workspace_analysis" }' in text
