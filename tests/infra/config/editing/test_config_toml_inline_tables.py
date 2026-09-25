from __future__ import annotations

from pathlib import Path

from tinysoul.infra.config import ConfigFileToml
from tinysoul.infra.json import to_json_object
from tinysoul.kernel.action.config import parse_action_settings


def test_config_toml_round_trips_inline_table_arrays(tmp_path: Path) -> None:
    path = tmp_path / "action.toml"
    document = ConfigFileToml(path)
    bindings = [
        {
            "consumer": "workspace.analyze.generate",
            "implementation": "llm_task",
            "target": {"task_profile": "workspace_analysis"},
        },
        {
            "consumer": "workspace.describe.generate",
            "implementation": "llm_task",
            "target": {"task_profile": "llm_action"},
        },
    ]
    document.set_value("action.models.bindings", bindings)
    document.save()
    loaded = ConfigFileToml(path)
    assert loaded.data["action"] == {"models": {"bindings": bindings}}
    action = loaded.data["action"]
    assert isinstance(action, dict)
    parsed = parse_action_settings(to_json_object(action))
    assert parsed.bindings[0].task_profile == "workspace_analysis"
    assert 'target = { task_profile = "workspace_analysis" }' in path.read_text(
        encoding="utf-8"
    )
