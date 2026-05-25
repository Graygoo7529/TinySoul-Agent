"""Tests for Step 3 peek/ack semantics: action records stay unread until state update succeeds."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider import client as client_module
from tinysoul.llm.provider.response import AIResponse
from tinysoul.llm.tasks.result import TaskResult
from tinysoul.llm.tasks.task import AITask
from tinysoul.loop.loop import LoopOutcome, QueryLoop
from tests.conftest import bootstrapped_registry
from tests.helpers.fakes import FakeLLMClient


class TestStep3AckSemantics:
    """Verify that action records are only marked read after successful state update."""

    def test_records_marked_read_after_successful_step3(
        self, bootstrapped_registry
    ):
        """When Step3 succeeds, unread action records become read."""
        fake_client = FakeLLMClient(
            [
                # Turn 1 Step 1: choose calculate
                '{"action_name": "calculate", "selection_reason": "Compute"}',
                # Turn 1 Step 2a: params
                '{"expression": "1+1"}',
                # Turn 1 Step 3: update
                '{"todo_operations": [], "milestone_operation": "no-change", "milestone_param": null}',
                # Turn 2 Step 1: choose calculate again (loop continues)
                '{"action_name": "calculate", "selection_reason": "Compute again"}',
                # Turn 2 Step 2a: params
                '{"expression": "2+2"}',
                # Turn 2 Step 3: update
                '{"todo_operations": [], "milestone_operation": "no-change", "milestone_param": null}',
            ]
        )

        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            client=fake_client,
            registry=bootstrapped_registry,
        )

        # Pre-seed an unread action record from a previous turn
        manager.query_state.record_action(
            action_name="previous",
            action_target="Previous",
            action_input={},
            action_result={"status": "ok"},
            turn=1,
        )
        assert not manager.query_state.action_record_list[0].read

        result = manager.query_loop(max_turns=2)

        assert result.status == LoopOutcome.Status.EXHAUSTED
        # After successful Step3 in each turn, all records should be read
        assert all(r.read for r in manager.query_state.action_record_list)

    def test_records_stay_unread_when_step3_llm_fails(self, monkeypatch, bootstrapped_registry):
        """When Step3 LLM call raises, action records remain unread for next turn."""
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        manager.query_state.record_action(
            action_name="calc", action_target="Compute", action_input={}, action_result={"value": "2"}, turn=1
        )
        call_count = [0]

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Step1 choose
                return TaskResult(
                    data={"action_name": "calculate", "selection_reason": "Need to compute"},
                    response=AIResponse(),
                )
            if call_count[0] == 2:
                # Step2a params
                return TaskResult(data={"expression": "1+1"}, response=AIResponse())
            # Step3 update — raise exception (max_turns=1 so no further turns)
            raise Exception("LLM service unavailable")

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=1)

        # Step3 failed, so all records (pre-seeded + calculate from Step2b) should be unread
        records = manager.query_state.get_action_record_list()
        assert all(not r.read for r in records)
        assert len(manager.query_state.peek_new_action_records()) == len(records)

    def test_records_stay_unread_when_step3_normalize_fails(self, monkeypatch, bootstrapped_registry):
        """When Step3 returns invalid JSON structure, records remain unread."""
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        manager.query_state.record_action(
            action_name="calc", action_target="Compute", action_input={}, action_result={"value": "2"}, turn=1
        )
        call_count = [0]

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return TaskResult(
                    data={"action_name": "calculate", "selection_reason": "Need to compute"},
                    response=AIResponse(),
                )
            if call_count[0] == 2:
                return TaskResult(data={"expression": "1+1"}, response=AIResponse())
            # Step3 update — return invalid structure (todo_operations is not a list)
            return TaskResult(
                data={"todo_operations": "not_a_list", "milestone_operation": "no-change"},
                response=AIResponse(),
            )

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=1)

        errors = manager.query_state.get_loop_error_list()
        assert any(e.step == "update_state" for e in errors)

        # All records remain unread because normalize failed before ack
        records = manager.query_state.get_action_record_list()
        assert all(not r.read for r in records)
        assert len(manager.query_state.peek_new_action_records()) == len(records)

    def test_new_records_from_step2b_are_peeked_and_acked(
        self, monkeypatch, bootstrapped_registry
    ):
        """End-to-end: action records produced in Step2b are peeked in Step3 and acked on success."""
        fake_client = FakeLLMClient(
            [
                # Turn 1 Step 1: choose calculate
                '{"action_name": "calculate", "selection_reason": "Compute"}',
                # Turn 1 Step 2a: params
                '{"expression": "1+1"}',
                # Turn 1 Step 3: update
                '{"todo_operations": [], "milestone_operation": "no-change", "milestone_param": null}',
            ]
        )

        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            client=fake_client,
            registry=bootstrapped_registry,
        )
        result = manager.query_loop(max_turns=2)

        assert result.status == LoopOutcome.Status.EXHAUSTED
        # The calculate action should have produced a record in Step2b
        records = manager.query_state.get_action_record_list()
        calc_records = [r for r in records if r.action_name == "calculate"]
        assert len(calc_records) == 1
        # After successful Step3, it should be read
        assert calc_records[0].read is True
