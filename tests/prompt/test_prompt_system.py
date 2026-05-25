from __future__ import annotations

from tinysoul.prompt import (
    FilePromptRef,
    InlinePromptSource,
    build_loop_system,
)
from tinysoul.prompt.loop import (
    get_choose_action_guide,
    get_generate_parameters_guide,
    get_query_loop_system,
    get_update_state_guide,
    home_loop_system_sources,
)


def test_loop_markdown_prompts_load():
    assert "structured query loop" in get_query_loop_system()
    assert "CHOOSE ACTION" in get_choose_action_guide()
    assert "GENERATE PARAMETERS" in get_generate_parameters_guide()
    assert "UPDATE STATE" in get_update_state_guide()


def test_build_loop_system_appends_builtin_query_loop_system():
    system = build_loop_system(
        [InlinePromptSource(name="runtime", content="RUNTIME SYSTEM")]
    )

    assert [item["content"] for item in system][0] == "RUNTIME SYSTEM"
    assert "structured query loop" in system[1]["content"]


def test_build_loop_system_supports_file_sources(tmp_path):
    (tmp_path / "AGENT.md").write_text("AGENT SYSTEM", encoding="utf-8")

    system = build_loop_system(
        [FilePromptRef(name="agent", root=tmp_path, path="AGENT.md")]
    )

    assert system[0]["content"] == "AGENT SYSTEM"
    assert "structured query loop" in system[1]["content"]


def test_home_loop_system_sources_default_order_and_optional():
    sources = home_loop_system_sources("home")

    assert [source.name for source in sources] == [
        "home_agent",
        "home_identity",
        "home_user",
    ]
    assert [source.path for source in sources] == [
        "AGENT.md",
        "IDENTITY.md",
        "USER.md",
    ]
    assert all(source.required is False for source in sources)
