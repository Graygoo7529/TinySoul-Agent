"""Unit tests for PromptBuilder and LLMPrompt serialization."""

from __future__ import annotations

import pytest

from tinysoul.llm.tasks.prompt import (
    Example,
    InputSpec,
    LLMPrompt,
    OutputConstraint,
    PromptBuilder,
)
from tests.helpers.fakes import FakeContextProvider


class TestLLMPromptSerialize:
    def test_includes_task_guide(self):
        prompt = LLMPrompt(
            task_guide="Do something",
            context={},
            input_spec=InputSpec(description="Input here", data={}),
            output_constraint=OutputConstraint(description="Output here"),
        )
        text = prompt.serialize()
        assert "=== TASK GUIDE ===" in text
        assert "Do something" in text

    def test_includes_context_when_present(self):
        prompt = LLMPrompt(
            task_guide="Task",
            context={"key": "value"},
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
        )
        text = prompt.serialize()
        assert "=== CONTEXT ===" in text
        assert '"key": "value"' in text

    def test_omits_context_when_empty(self):
        prompt = LLMPrompt(
            task_guide="Task",
            context={},
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
        )
        text = prompt.serialize()
        assert "=== CONTEXT ===" not in text

    def test_includes_input_description_and_data(self):
        prompt = LLMPrompt(
            task_guide="Task",
            context={},
            input_spec=InputSpec(description="Describe input", data={"x": 1}),
            output_constraint=OutputConstraint(description="Out"),
        )
        text = prompt.serialize()
        assert "=== INPUT ===" in text
        assert "Describe input" in text
        assert '"x": 1' in text

    def test_includes_output_constraint_and_schema(self):
        schema = {"type": "object"}
        prompt = LLMPrompt(
            task_guide="Task",
            context={},
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Must be JSON", schema=schema),
        )
        text = prompt.serialize()
        assert "=== OUTPUT CONSTRAINT ===" in text
        assert "Must be JSON" in text
        assert '"type": "object"' in text

    def test_includes_examples(self):
        prompt = LLMPrompt(
            task_guide="Task",
            context={},
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            examples=[
                Example(input={"a": 1}, output={"b": 2}),
            ],
        )
        text = prompt.serialize()
        assert "=== EXAMPLES ===" in text
        assert "Example 1:" in text
        assert '"a": 1' in text
        assert '"b": 2' in text

    def test_parts_are_in_correct_order(self):
        prompt = LLMPrompt(
            task_guide="T",
            context={"c": 1},
            input_spec=InputSpec(description="I", data={"d": 2}),
            output_constraint=OutputConstraint(description="O", schema={"s": 3}),
            examples=[Example(input={"e": 4}, output={"f": 5})],
        )
        text = prompt.serialize()
        tg_pos = text.index("TASK GUIDE")
        ctx_pos = text.index("CONTEXT")
        inp_pos = text.index("INPUT")
        out_pos = text.index("OUTPUT CONSTRAINT")
        ex_pos = text.index("EXAMPLES")
        assert tg_pos < ctx_pos < inp_pos < out_pos < ex_pos


class TestPromptBuilderBuild:
    def test_injects_shared_context_fields(self):
        provider = FakeContextProvider(
            query_events="compute weight",
            loop_target="get dog weight",
            current_turn=3,
        )
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Choose action",
            input_spec=InputSpec(description="Available actions", data={"actions": []}),
            output_constraint=OutputConstraint(description="JSON only"),
        )
        assert prompt.context["query_events"] == "compute weight"
        assert prompt.context["loop_target"] == "get dog weight"
        assert prompt.context["current_turn"] == 3

    def test_injects_current_state_from_provider(self):
        provider = FakeContextProvider()
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Update state",
            input_spec=InputSpec(description="Records", data={}),
            output_constraint=OutputConstraint(description="JSON"),
        )
        assert "current_state" in prompt.context
        assert prompt.context["current_state"]["current_turn"] == 1

    def test_injects_workspace_from_provider(self, tmp_path):
        from tests.helpers.factories import WorkspaceBuilder

        tmp = tmp_path / "fake_ws"
        ws = WorkspaceBuilder(str(tmp)).with_file("a.md", "# A").build()
        provider = FakeContextProvider(_workspace=ws)
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
        )
        assert "workspace" in prompt.context
        assert prompt.context["workspace"]["resources"]

    def test_extra_context_merges_into_shared_context(self):
        provider = FakeContextProvider()
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            extra_context={"custom_key": "custom_value"},
        )
        assert prompt.context["custom_key"] == "custom_value"

    def test_extra_context_can_override_shared_field(self):
        provider = FakeContextProvider(query_events="original")
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            extra_context={"query_events": "overridden"},
        )
        assert prompt.context["query_events"] == "overridden"

    def test_include_context_none_includes_all_fields(self):
        provider = FakeContextProvider()
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            include_context=None,
        )
        assert "query_events" in prompt.context
        assert "loop_target" in prompt.context
        assert "current_state" in prompt.context
        assert "current_turn" in prompt.context

    def test_include_context_filters_top_level_fields(self):
        provider = FakeContextProvider()
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            include_context=["query_events", "current_turn"],
        )
        assert "query_events" in prompt.context
        assert "current_turn" in prompt.context
        assert "loop_target" not in prompt.context
        assert "current_state" not in prompt.context
        assert "workspace" not in prompt.context

    def test_include_context_filters_nested_fields(self):
        provider = FakeContextProvider()
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            include_context=["query_events", "current_state.todo_list", "current_state.milestone_list"],
        )
        assert "query_events" in prompt.context
        cs = prompt.context["current_state"]
        assert "todo_list" in cs
        assert "milestone_list" in cs
        assert "action_record_list" not in cs
        assert "feedback_error_list" not in cs
        assert "current_turn" not in prompt.context

    def test_include_context_parent_field_overrides_nested(self):
        provider = FakeContextProvider()
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            include_context=["current_state", "current_state.todo_list"],
        )
        cs = prompt.context["current_state"]
        assert "todo_list" in cs
        assert "action_record_list" in cs
        assert "feedback_error_list" in cs

    def test_include_context_empty_list_returns_empty_context(self):
        provider = FakeContextProvider(query_events="test")
        builder = PromptBuilder(provider)
        prompt = builder.build(
            task_guide="Task",
            input_spec=InputSpec(description="In", data={}),
            output_constraint=OutputConstraint(description="Out"),
            include_context=[],
        )
        assert prompt.context == {}
