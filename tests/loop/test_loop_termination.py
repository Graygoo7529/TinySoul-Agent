"""Unit tests for QueryLoop termination conditions."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider import client as client_module
from tinysoul.llm.provider.response import AIResponse
from tinysoul.llm.tasks.result import TaskResult
from tinysoul.llm.tasks.task import AITask
from tinysoul.loop.loop import LoopOutcome, QueryLoop
from tinysoul.context.workspace import Workspace
from tests.conftest import bootstrapped_registry
from tests.helpers.fakes import FakeLLMClient


class TestMaxTurnsExhaustion:
    def test_returns_finished_false_when_max_turns_reached(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        call_count = [0]

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            call_count[0] += 1
            if call_count[0] % 3 == 1:
                return TaskResult(
                    data={"action_name": "calculate", "selection_reason": "Compute"},
                    response=AIResponse(),
                )
            if call_count[0] % 3 == 2:
                return TaskResult(data={"expression": "1+1"}, response=AIResponse())
            return TaskResult(
                data={
                    "todo_operations": [],
                    "milestone_operation": "no-change",
                    "milestone_param": None,
                },
                response=AIResponse(),
            )

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=3)
        assert result.status == LoopOutcome.Status.EXHAUSTED
        assert result.completed_turns == 3


class TestAnswerActionTermination:
    def test_terminates_via_answer_action(self, monkeypatch, bootstrapped_registry, tmp_path):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate", "answer"],
            registry=bootstrapped_registry,
            workspace=Workspace(workspace_location=str(tmp_path)),
        )
        call_count = [0]

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return TaskResult(
                    data={"action_name": "answer", "selection_reason": "Provide answer"},
                    response=AIResponse(),
                )
            if call_count[0] == 2:
                return TaskResult(
                    data={"instruction": "Answer", "reference_accesses": []},
                    response=AIResponse(),
                )
            return TaskResult(
                data={"answer_text": "The answer is 42", "confidence": "high", "references": []},
                response=AIResponse(),
            )

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=10)
        assert result.status == LoopOutcome.Status.COMPLETED
        assert result.completed_turns == 1
        assert "42" in result.answer


class TestKeyboardInterruptTermination:
    def test_returns_interrupted_true(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=5)
        assert result.status == LoopOutcome.Status.INTERRUPTED
