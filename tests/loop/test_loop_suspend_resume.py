"""Tests for QueryLoop SUSPEND and resume."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider import client as client_module
from tinysoul.llm.provider.response import AIResponse
from tinysoul.llm.tasks.result import TaskResult
from tinysoul.llm.tasks.task import AITask
from tinysoul.loop.loop import LoopOutcome, QueryLoop
from tinysoul.loop.query import QueryEventRole
from tinysoul.context.workspace import Workspace
from tests.conftest import bootstrapped_registry
from tests.helpers.fakes import FakeLLMClient


class TestAskUserSuspend:
    def test_suspends_and_records_question(self, monkeypatch, bootstrapped_registry, tmp_path):
        responses = [
            '{"action_name": "ask_user", "selection_reason": "Need clarification"}',
            '{"question": "What are the breeds?", "context": "Need breeds to look up weights"}',
            # No Step 3 because SUSPEND
        ]
        fake_client = FakeLLMClient(responses)
        monkeypatch.setattr(
            client_module._AIClientSingleton, "_instance", fake_client
        )

        ws = Workspace(workspace_location=str(tmp_path))
        manager = QueryLoop(
            initial_query="What is combined weight?",
            loop_target="Compute combined weight",
            available_action_names=["ask_user", "average_dog_weight", "answer"],
            client=fake_client,
            registry=bootstrapped_registry,
            workspace=ws,
        )
        result = manager.query_loop(max_turns=5)

        assert result.status == LoopOutcome.Status.SUSPENDED
        assert result.pending_question is not None
        assert result.pending_question["question"] == "What are the breeds?"
        assert manager.is_suspended() is True

        # Question recorded in history
        history = manager.query_context.query_events.items
        ask_items = [h for h in history if h.role == QueryEventRole.INQUIRY]
        assert len(ask_items) == 1
        assert ask_items[0].content == "What are the breeds?"

    def test_resume_continues_execution(self, monkeypatch, bootstrapped_registry, tmp_path):
        responses = [
            # Turn 1: ask_user
            '{"action_name": "ask_user", "selection_reason": "Need clarification"}',
            '{"question": "What breed?", "context": "Need breed"}',
            # Turn 2: answer (after resume)
            '{"action_name": "answer", "selection_reason": "Provide answer"}',
            '{"instruction": "Answer", "reference_accesses": []}',
            '{"answer_text": "42 lbs", "confidence": "high", "references": []}',
        ]
        fake_client = FakeLLMClient(responses)
        monkeypatch.setattr(
            client_module._AIClientSingleton, "_instance", fake_client
        )

        ws = Workspace(workspace_location=str(tmp_path))
        manager = QueryLoop(
            initial_query="What is weight?",
            loop_target="Get weight",
            available_action_names=["ask_user", "answer"],
            client=fake_client,
            registry=bootstrapped_registry,
            workspace=ws,
        )

        # First run suspends
        result = manager.query_loop(max_turns=5)
        assert result.status == LoopOutcome.Status.SUSPENDED

        # Resume with user response
        result = manager.resume("Border Collie")
        assert result.status == LoopOutcome.Status.COMPLETED
        assert "42 lbs" in result.answer
        assert manager.is_suspended() is False

        # History contains user response
        history = manager.query_context.query_events.items
        response_items = [h for h in history if h.role == QueryEventRole.RESPONSE]
        assert len(response_items) == 1
        assert response_items[0].content == "Border Collie"
        assert response_items[0].ask_context == "What breed?"

    def test_resume_without_suspend_returns_aborted(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            registry=bootstrapped_registry,
        )
        result = manager.resume("answer")
        assert result.status == LoopOutcome.Status.ABORTED
        assert result.error_type == "ResumeStateError"
        assert result.error_message is not None
        assert "not in suspended state" in result.error_message
        assert result.completed_turns == 0
        assert result.final_state is not None
