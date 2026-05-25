"""Tests for LLM action system prompt assembly."""

from __future__ import annotations

from tinysoul.prompt.action import (
    build_llm_action_system,
    get_action_execution_context,
)


class FakeContext:
    def get_loop_level_system(self):
        return [
            {"role": "system", "content": "BASIC SYSTEM"},
            {"role": "system", "content": "QUERY LOOP SYSTEM"},
        ]


def test_build_llm_action_system_order():
    system = build_llm_action_system(
        FakeContext(),
        action_system=[{"role": "system", "content": "ACTION SYSTEM"}],
    )

    assert [item["content"] for item in system] == [
        "BASIC SYSTEM",
        "QUERY LOOP SYSTEM",
        get_action_execution_context(),
        "ACTION SYSTEM",
    ]


def test_build_llm_action_system_without_loop_provider():
    system = build_llm_action_system(
        object(),
        action_system=[{"role": "system", "content": "ACTION SYSTEM"}],
    )

    assert [item["content"] for item in system] == [
        get_action_execution_context(),
        "ACTION SYSTEM",
    ]
