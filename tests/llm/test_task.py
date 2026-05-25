"""Unit tests for AITask — prompt → AI call → interpret pipeline."""

from __future__ import annotations

import pytest

from tinysoul.llm.tasks.interpreter import Interpreter
from tinysoul.llm.tasks.prompt import InputSpec, LLMPrompt, OutputConstraint
from tinysoul.llm.tasks.result import TaskResult
from tinysoul.llm.tasks.task import AITask
from tinysoul.llm.provider.config import LLMProfileName
from tests.helpers.fakes import FakeLLMClient


class TestAITaskRun:
    def test_pipeline_returns_parsed_data_and_raw_response(self):
        client = FakeLLMClient(responses=['{"result": 42}'])
        task = AITask(
            prompt=LLMPrompt(
                task_guide="Compute",
                context={},
                input_spec=InputSpec(description="Expr", data={"expression": "6*7"}),
                output_constraint=OutputConstraint(description="JSON"),
            ),
            interpreter=Interpreter(),
            client=client,
        )
        result = task.run(profile=LLMProfileName.STEP1)
        assert isinstance(result, TaskResult)
        assert result.data == {"result": 42}
        assert result.response.content == '{"result": 42}'

    def test_prompt_is_serialized_and_sent(self):
        client = FakeLLMClient(responses=['{"ok": true}'])
        task = AITask(
            prompt=LLMPrompt(
                task_guide="Task",
                context={"ctx": 1},
                input_spec=InputSpec(description="In", data={"x": 2}),
                output_constraint=OutputConstraint(description="Out"),
            ),
            interpreter=Interpreter(),
            client=client,
        )
        task.run(profile=LLMProfileName.STEP1)
        client.assert_call_count(1)
        client.assert_user_prompt_contains(0, "Task")
        client.assert_user_prompt_contains(0, "ctx")

    def test_system_messages_are_passed(self):
        client = FakeLLMClient(responses=['{}'])
        task = AITask(
            prompt=LLMPrompt(
                task_guide="T",
                context={},
                input_spec=InputSpec(description="I", data={}),
                output_constraint=OutputConstraint(description="O"),
            ),
            interpreter=Interpreter(),
            client=client,
        )
        system = [{"role": "system", "content": "You are a calculator"}]
        task.run(profile=LLMProfileName.STEP1, system=system)
        client.assert_system_contains(0, "You are a calculator")

    def test_interpret_failure_propagates(self):
        client = FakeLLMClient(responses=["not json"])
        task = AITask(
            prompt=LLMPrompt(
                task_guide="T",
                context={},
                input_spec=InputSpec(description="I", data={}),
                output_constraint=OutputConstraint(description="O"),
            ),
            interpreter=Interpreter(),
            client=client,
        )
        from tinysoul.trap import LLMResponseParseError

        with pytest.raises(LLMResponseParseError):
            task.run(profile=LLMProfileName.STEP1)

    def test_timeout_is_passed_to_client(self):
        client = FakeLLMClient(responses=['{"result": 42}'])
        task = AITask(
            prompt=LLMPrompt(
                task_guide="Compute",
                context={},
                input_spec=InputSpec(description="Expr", data={}),
                output_constraint=OutputConstraint(description="JSON"),
            ),
            interpreter=Interpreter(),
            client=client,
        )
        from tinysoul.llm.provider.config import ChatConfig
        task.run(profile=LLMProfileName.STEP1, config=ChatConfig(timeout=30.0))
        assert client.calls[0]["config"].timeout == 30.0
