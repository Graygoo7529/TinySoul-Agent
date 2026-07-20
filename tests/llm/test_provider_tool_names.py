from __future__ import annotations

import re

from tinysoul.llm.provider.openai_sdk.tool_names import ProviderToolNameMap


def test_provider_tool_name_map_keeps_safe_names_and_maps_dotted_names() -> None:
    name_map = ProviderToolNameMap.from_names(
        ("read_file", "workspace.scan", "1leading", "\u5de5\u5177.read")
    )

    assert name_map.to_provider_name("read_file") == "read_file"
    assert name_map.to_provider_name("workspace.scan") == "workspace_scan"
    assert name_map.to_provider_name("1leading") == "_1leading"
    for tinysoul_name in ("workspace.scan", "1leading", "\u5de5\u5177.read"):
        provider_name = name_map.to_provider_name(tinysoul_name)
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", provider_name)
        assert name_map.to_tinysoul_name(provider_name) == tinysoul_name


def test_provider_tool_name_map_resolves_alias_collisions() -> None:
    name_map = ProviderToolNameMap.from_names(
        ("workspace.scan", "workspace_scan", "workspace/scan")
    )

    provider_names = {
        name_map.to_provider_name(name)
        for name in ("workspace.scan", "workspace_scan", "workspace/scan")
    }
    assert len(provider_names) == 3
    assert name_map.to_provider_name("workspace_scan") == "workspace_scan"
    for provider_name in provider_names:
        assert name_map.to_provider_name(
            name_map.to_tinysoul_name(provider_name)
        ) == provider_name


def test_provider_tool_name_map_bounds_long_names_and_leaves_unknown_output() -> None:
    tinysoul_name = "workspace." + "very_long_action_name_" * 8
    name_map = ProviderToolNameMap.from_names((tinysoul_name,))

    provider_name = name_map.to_provider_name(tinysoul_name)
    assert len(provider_name) == 64
    assert name_map.to_tinysoul_name(provider_name) == tinysoul_name
    assert name_map.to_tinysoul_name("unknown_tool") == "unknown_tool"
