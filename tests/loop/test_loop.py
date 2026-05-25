"""End-to-end mock tests for QueryLoop using FakeLLMClient."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider import client as client_module
from tinysoul.llm.provider.response import AIResponse
from tinysoul.llm.tasks.result import TaskResult
from tinysoul.llm.tasks.task import AITask
from tinysoul.loop.loop import LoopOutcome, QueryLoop
from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import make_handler
from tinysoul.context.state import TaskStatus
from tinysoul.context.workspace import Workspace
from tests.conftest import bootstrapped_registry
from tests.helpers.fakes import FakeLLMClient


ACTION_JSON_DYNAMIC_NOOP = (
    '{"name": "dynamic_noop", "description": "Dynamic no-op test action", '
    '"cluster": {"type": "NATIVE", "domain": "TEST"}, '
    '"profile": {"action_intention": "EXECUTION", '
    '"action_environment_effect": "READ_ONLY", '
    '"action_mode": "SINGLE_RUN", "llm_dependency": "NONE"}, '
    '"contract": {"applicability": {"mode": "ALWAYS_CONSIDER", "conditions": []}, '
    '"preconditions": [], '
    '"postconditions": {"logical_state_effects": [], "physical_environment_effects": []}}, '
    '"detail": {"parameter_schema": {"type": "object"}, '
    '"examples": [], "edge_case_handling": []}}'
)


class DynamicNoopExecutor(ActionExecutor):
    def execute(self, action_input, context_provider, run_config):
        return {"ok": True}


def dynamic_noop_factory():
    return make_handler(
        "dynamic_noop",
        ACTION_JSON_DYNAMIC_NOOP,
        DynamicNoopExecutor(),
    )


class TestDogWeightQueryMock:
    """Simulate a 3-turn query loop that computes combined dog weight."""

    def test_combined_dog_weight_mock(self, monkeypatch, bootstrapped_registry, tmp_path):
        """Uses answer action to terminate instead of finished flag."""
        responses = [
            # Turn 1 Step 1: choose
            '{"action_name": "average_dog_weight", "selection_reason": "Need border collie weight"}',
            # Turn 1 Step 2a: params
            '{"breed": "Border Collie"}',
            # Turn 1 Step 3: update
            '{"todo_operations": [{"operation": "add", "key": "get_scottish_weight", "description": "Get Scottish Terrier weight"}], "milestone_operation": "no-change", "milestone_param": null}',
            # Turn 2 Step 1: choose
            '{"action_name": "average_dog_weight", "selection_reason": "Need scottish terrier weight"}',
            # Turn 2 Step 2a: params
            '{"breed": "Scottish Terrier"}',
            # Turn 2 Step 3: update
            '{"todo_operations": [{"operation": "complete", "key": "get_scottish_weight"}], "milestone_operation": "no-change", "milestone_param": null}',
            # Turn 3 Step 1: choose answer
            '{"action_name": "answer", "selection_reason": "Provide final answer"}',
            # Turn 3 Step 2a: params for answer
            '{"instruction": "Summarize the weight findings", "reference_accesses": []}',
            # Turn 3 Step 2b: answer executor internal LLM
            '{"answer_text": "Combined weight is 57 lbs", "confidence": "high", "references": ["average_dog_weight"]}',
        ]

        fake_client = FakeLLMClient(responses)
        # Inject fake client as global singleton so OneStepAIExecutor can use it
        monkeypatch.setattr(
            client_module._AIClientSingleton, "_instance", fake_client
        )

        ws = Workspace(workspace_location=str(tmp_path))

        manager = QueryLoop(
            initial_query="I have 2 dogs, a border collie and a scottish terrier. What is their combined weight",
            loop_target="Compute combined weight of a border collie and a scottish terrier",
            available_action_names=["average_dog_weight", "answer"],
            client=fake_client,
            registry=bootstrapped_registry,
            workspace=ws,
        )
        result = manager.query_loop(max_turns=5)

        assert result.status == LoopOutcome.Status.COMPLETED
        assert result.completed_turns == 3
        assert "57 lbs" in result.answer

        records = manager.query_state.get_action_record_list()
        assert len(records) == 3
        assert records[0].action_name == "average_dog_weight"
        assert records[1].action_name == "average_dog_weight"
        assert records[2].action_name == "answer"


class TestSharedRegistryAcrossLoops:
    def test_second_loop_can_opt_into_dynamic_action_registered_by_first_loop(
        self, bootstrapped_registry
    ):
        loop_a = QueryLoop(
            initial_query="register a dynamic action",
            loop_target="register",
            available_action_names=["answer"],
            registry=bootstrapped_registry,
        )

        loop_a.query_action.register_action(
            "dynamic_noop",
            ACTION_JSON_DYNAMIC_NOOP,
            dynamic_noop_factory,
        )

        loop_b = QueryLoop(
            initial_query="use the dynamic action",
            loop_target="use",
            available_action_names=["dynamic_noop", "answer"],
            registry=bootstrapped_registry,
        )

        assert loop_b.query_action.is_action_available("dynamic_noop")

    def test_second_loop_does_not_see_dynamic_action_unless_allowlisted(
        self, bootstrapped_registry
    ):
        loop_a = QueryLoop(
            initial_query="register a dynamic action",
            loop_target="register",
            available_action_names=["answer"],
            registry=bootstrapped_registry,
        )

        loop_a.query_action.register_action(
            "dynamic_noop",
            ACTION_JSON_DYNAMIC_NOOP,
            dynamic_noop_factory,
        )

        loop_b = QueryLoop(
            initial_query="do not expose the dynamic action",
            loop_target="use",
            available_action_names=["answer"],
            registry=bootstrapped_registry,
        )

        assert bootstrapped_registry.is_registered("dynamic_noop")
        assert not loop_b.query_action.is_action_available("dynamic_noop")


class TestQueryLoopErrorRecoveryMock:
    def test_step1_bad_json_records_error_and_continues(self, bootstrapped_registry):
        fake_client = FakeLLMClient(
            [
                "not valid json",
                '{"action_name": "calculate", "selection_reason": "Compute"}',
                '{"expression": "1+1"}',
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

        errors = manager.query_state.get_loop_error_list()
        assert len(errors) == 1
        assert errors[0].step == "choose_action"
        assert "LLMResponseParseError" in errors[0].error_type
        assert result.status == LoopOutcome.Status.EXHAUSTED

    def test_step2_error_records_loop_error_and_continues(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        call_count = [0]

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            call_count[0] += 1
            if call_count[0] in (1, 3):
                return TaskResult(
                    data={"action_name": "calculate", "selection_reason": "Need to compute"},
                    response=AIResponse(),
                )
            raise Exception("Bad JSON")

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=2)

        errors = manager.query_state.get_loop_error_list()
        assert len(errors) == 2
        assert all(e.step == "generate_parameters" for e in errors)
        assert result.status == LoopOutcome.Status.EXHAUSTED

    def test_step3_error_records_loop_error_and_resets_updates(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        manager.query_state.record_action("calc", "Compute", {}, {"value": "2", "expression": "1+1"}, turn=1)
        call_count = [0]

        def fake_llm_task_execute(self, system=None, config=None, **kwargs):
            call_count[0] += 1
            if call_count[0] in (1, 4):
                return TaskResult(
                    data={"action_name": "calculate", "selection_reason": "Need to compute"},
                    response=AIResponse(),
                )
            if call_count[0] in (2, 5):
                return TaskResult(data={"expression": "1+1"}, response=AIResponse())
            if call_count[0] == 3:
                return TaskResult(
                    data={
                        "todo_operations": [],
                        "milestone_operation": "no-change",
                        "milestone_param": None,
                    },
                    response=AIResponse(),
                )
            raise Exception("Parse error")

        monkeypatch.setattr(AITask, "run", fake_llm_task_execute)
        result = manager.query_loop(max_turns=2)

        errors = manager.query_state.get_loop_error_list()
        assert len(errors) == 1
        assert errors[0].step == "update_state"
        assert result.status == LoopOutcome.Status.EXHAUSTED
        assert result.completed_turns == 2
