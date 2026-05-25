"""Unit tests for individual QueryLoop steps using monkeypatched AITask.run."""

from __future__ import annotations

import time

import pytest

from tinysoul.action.framework.handler import ActionMode
from tinysoul.action.handlers.monitor.stop_ongoing_action import StopOngoingActionExecutor
from tinysoul.action.handlers.monitor.monitor import MonitorExecutor
from tinysoul.trap.signal import SignalType
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider
from tinysoul.llm.provider.response import AIResponse
from tinysoul.llm.tasks.result import TaskResult
from tinysoul.llm.tasks.task import AITask
from tinysoul.loop.loop import QueryLoop
from tinysoul.loop.parallel_dispatcher import ActionSpec
from tests.conftest import bootstrapped_registry


def fake_task_result(data):
    def _run(self, *, profile, system=None, config=None):
        return TaskResult(data=data, response=AIResponse())

    return _run


class TestStep1ChooseAction:
    def test_selects_action_and_records_target(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )
        monkeypatch.setattr(
            AITask,
            "run",
            fake_task_result(
                {"action_name": "calculate", "selection_reason": "Need sum"}
            ),
        )
        result = manager._step1_choose_action()
        assert len(result) == 1
        assert result[0].name == "calculate"
        assert result[0].target == "Need sum"

    def test_selects_multiple_actions(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )
        monkeypatch.setattr(
            AITask,
            "run",
            fake_task_result(
                {
                    "actions": [
                        {"action_name": "calculate", "selection_reason": "Need sum"},
                        {"action_name": "scan_workspace", "selection_reason": "Check files"},
                    ]
                }
            ),
        )
        result = manager._step1_choose_action()
        assert len(result) == 2
        assert result[0].name == "calculate"
        assert result[1].name == "scan_workspace"

    def test_raises_validation_error_when_action_name_missing(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )
        monkeypatch.setattr(
            AITask,
            "run",
            fake_task_result({"selection_reason": "no name"}),
        )
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="Missing 'action_name'"):
            manager._step1_choose_action()


class TestStep2aGenerateParameters:
    def test_generates_action_args(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        monkeypatch.setattr(
            AITask,
            "run",
            fake_task_result({"expression": "2 + 2"}),
        )
        specs = [ActionSpec(name="calculate", target="Compute", args={})]
        result = manager._step2a_generate_parameters(specs)
        assert len(result) == 1
        assert result[0].args == {"expression": "2 + 2"}


class TestStep2bExecuteActions:
    def test_executes_and_records_action(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        specs = [ActionSpec(name="calculate", target="Compute sum", args={"expression": "3 + 3"})]
        success = manager._step2b_execute_actions(specs)
        assert success is True
        signals = manager._signal_bus.consume()
        for signal in signals:
            manager._error_trap.route(signal)

        records = manager.query_state.get_action_record_list()
        assert len(records) == 1
        assert records[0].action_name == "calculate"

    def test_executes_parallel_actions(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate", "average_dog_weight"],
            registry=bootstrapped_registry,
        )
        specs = [
            ActionSpec(name="calculate", target="Sum", args={"expression": "1 + 1"}),
            ActionSpec(name="average_dog_weight", target="Weight", args={"breed": "labrador"}),
        ]
        success = manager._step2b_execute_actions(specs)
        assert success is True
        signals = manager._signal_bus.consume()
        for signal in signals:
            manager._error_trap.route(signal)

        records = manager.query_state.get_action_record_list()
        assert len(records) == 2


class TestOngoingActionLifecycle:
    def test_step1_sets_ongoing_mode_for_monitor(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["monitor"],
            registry=bootstrapped_registry,
        )
        monkeypatch.setattr(
            AITask,
            "run",
            fake_task_result(
                {"action_name": "monitor", "selection_reason": "Need to observe"}
            ),
        )
        result = manager._step1_choose_action()
        assert len(result) == 1
        assert result[0].name == "monitor"
        assert result[0].mode == ActionMode.ONGOING

    def test_monitor_execution_lifecycle(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["monitor"],
            registry=bootstrapped_registry,
        )
        specs = [
            ActionSpec(
                name="monitor",
                target="Observe",
                args={"interval": 0.1, "max_ticks": 1},
                mode=ActionMode.ONGOING,
            )
        ]
        success = manager._step2b_execute_actions(specs)
        assert success is True

        # Drain ONGOING_STARTED signal immediately
        signals = manager._signal_bus.consume()
        for signal in signals:
            manager._error_trap.route(signal)

        ongoing = manager.query_state.get_ongoing_action_list()
        assert len(ongoing) == 1
        assert ongoing[0]["action_name"] == "monitor"
        assert ongoing[0]["execution_id"] == specs[0].execution_id

        # Wait for background tick and ONGOING_COMPLETED
        time.sleep(0.5)
        signals = manager._signal_bus.consume()
        for signal in signals:
            manager._error_trap.route(signal)

        assert manager.query_state.get_ongoing_action_list() == []

        # Verify that ticks were recorded as action records
        records = manager.query_state.get_action_record_list()
        monitor_records = [r for r in records if r.action_name == "monitor"]
        assert len(monitor_records) >= 2  # ONGOING_STARTED + at least one tick/complete

    def test_monitor_background_lifetime_ignores_startup_run_config_deadline(self):
        emitted = []

        class CapturingContext(FakeContextProvider):
            def emit_signal(self, signal):
                emitted.append(signal)

        cfg = run_config("monitor", timeout=0.01)
        ctx = CapturingContext()
        result = MonitorExecutor().execute(
            {"interval": 0.05, "max_ticks": 1},
            ctx,
            cfg,
        )

        assert result["status"] == "ongoing_started"
        time.sleep(0.2)

        types = [signal.type for signal in emitted]
        assert SignalType.ONGOING_TICK in types
        assert SignalType.ONGOING_COMPLETED in types
        assert SignalType.ACTION_CANCELLED not in types

    def test_stop_ongoing_action_requests_monitor_termination(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["monitor", "stop_ongoing_action"],
            registry=bootstrapped_registry,
        )
        specs = [
            ActionSpec(
                name="monitor",
                target="Observe",
                args={"interval": 0.05, "max_ticks": 20},
                mode=ActionMode.ONGOING,
            )
        ]
        assert manager._step2b_execute_actions(specs) is True

        for signal in manager._signal_bus.consume():
            manager._error_trap.route(signal)
        execution_id = specs[0].execution_id
        assert manager.query_state.get_ongoing_action_list()[0]["execution_id"] == execution_id

        result = StopOngoingActionExecutor().execute(
            {"execution_id": execution_id},
            manager.query_context,
            run_config("stop_ongoing_action"),
        )
        assert result["status"] == "termination_requested"

        time.sleep(0.2)
        for signal in manager._signal_bus.consume():
            manager._error_trap.route(signal)
        assert manager.query_state.get_ongoing_action_list() == []

        records = manager.query_state.get_action_record_list()
        completed = [
            r
            for r in records
            if r.execution_id == execution_id
            and r.action_result.get("status") == "terminated"
        ]
        assert completed

    def test_loop_completion_requests_ongoing_shutdown(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["monitor"],
            registry=bootstrapped_registry,
        )
        specs = [
            ActionSpec(
                name="monitor",
                target="Observe",
                args={"interval": 5.0, "max_ticks": 20},
                mode=ActionMode.ONGOING,
            )
        ]
        assert manager._step2b_execute_actions(specs) is True

        for signal in manager._signal_bus.consume():
            manager._error_trap.route(signal)
        execution_id = specs[0].execution_id
        assert manager.query_state.get_ongoing_action_list()[0]["execution_id"] == execution_id

        manager._shutdown_ongoing_actions()

        assert manager.query_state.get_ongoing_action_list() == []
        records = manager.query_state.get_action_record_list()
        shutdown_records = [
            r
            for r in records
            if r.execution_id == execution_id
            and r.action_result.get("reason") == "shutdown"
        ]
        assert shutdown_records


class TestStep3UpdateState:
    def test_applies_todo_and_milestone_updates(self, monkeypatch, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )
        manager.query_state.record_action("calc", "Compute", {}, {"value": "2", "expression": "1+1"}, turn=1)
        monkeypatch.setattr(
            AITask,
            "run",
            fake_task_result(
                {
                    "todo_operations": [
                        {"operation": "add", "key": "verify", "description": "Verify"}
                    ],
                    "milestone_operation": "add",
                    "milestone_param": "Phase 1 done",
                }
            ),
        )
        updates = manager._step3_update_state()
        assert "Phase 1 done" in manager.query_state.get_milestones()
        pending = manager.query_state.get_todos()
        assert any(t.semantic_key == "verify" for t in pending)
