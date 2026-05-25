"""Tests for ParallelDispatcher failure counting, timeout semantics, and late-result filtering."""

from __future__ import annotations

import time

import pytest

from tinysoul.loop.loop import QueryLoop
from tinysoul.loop.parallel_dispatcher import ActionSpec
from tinysoul.trap.signal import SignalType
from tests.conftest import bootstrapped_registry


class TestParallelDispatcherOutcome:
    """Verify that dispatch statistics reflect actual action outcomes."""

    def test_failed_action_counts_as_failed(self, monkeypatch, bootstrapped_registry):
        """An action that raises must be counted as failed, not completed."""
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )

        def fake_execute(name, args, context_provider, run_config):
            raise RuntimeError("Simulated action failure")

        monkeypatch.setattr(manager.query_action, "execute", fake_execute)

        specs = [
            ActionSpec(name="calculate", target="Compute", args={"expression": "1+1"})
        ]
        outcome = manager._parallel_dispatcher.dispatch(
            specs, manager.query_context, turn=1, timeout=5.0
        )

        assert outcome.total == 1
        assert outcome.completed == 0
        assert outcome.failed == 1
        assert outcome.timed_out == 0

        # SignalBus should contain exactly one ACTION_FAILED signal
        signals = manager._signal_bus.consume()
        assert len(signals) == 1
        assert signals[0].type == SignalType.ACTION_FAILED
        assert signals[0].execution_id

    def test_timeout_action_counts_as_timed_out(self, monkeypatch, bootstrapped_registry):
        """An action that exceeds batch timeout must be counted as timed_out."""
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )

        def fake_execute(name, args, context_provider, run_config):
            time.sleep(0.2)
            return {"value": "2"}

        monkeypatch.setattr(manager.query_action, "execute", fake_execute)

        specs = [
            ActionSpec(name="calculate", target="Compute", args={"expression": "1+1"})
        ]
        started = time.monotonic()
        outcome = manager._parallel_dispatcher.dispatch(
            specs, manager.query_context, turn=1, timeout=0.01
        )
        elapsed = time.monotonic() - started

        assert outcome.total == 1
        assert outcome.completed == 0
        assert outcome.failed == 0
        assert outcome.timed_out == 1
        assert elapsed < 0.15

        # SignalBus should contain exactly one ACTION_TIMEOUT signal
        signals = manager._signal_bus.consume()
        assert len(signals) == 1
        assert signals[0].type == SignalType.ACTION_TIMEOUT
        assert signals[0].execution_id == specs[0].execution_id

    def test_timed_out_action_late_result_ignored(self, monkeypatch, bootstrapped_registry):
        """
        If an action is still running when the batch timeout fires, the
        dispatcher emits ACTION_TIMEOUT.  The late ACTION_COMPLETED (or
        ACTION_FAILED) that arrives after the timeout must be ignored so
        that the action is not double-recorded.
        """
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate"],
            registry=bootstrapped_registry,
        )

        def fake_execute(name, args, context_provider, run_config):
            # Starts immediately but finishes *after* the dispatch timeout.
            time.sleep(0.05)
            return {"value": "2"}

        monkeypatch.setattr(manager.query_action, "execute", fake_execute)

        specs = [
            ActionSpec(name="calculate", target="Compute", args={"expression": "1+1"})
        ]
        outcome = manager._parallel_dispatcher.dispatch(
            specs, manager.query_context, turn=1, timeout=0.01
        )

        assert outcome.total == 1
        assert outcome.completed == 0
        assert outcome.failed == 0
        assert outcome.timed_out == 1

        # SignalBus must contain ONLY the ACTION_TIMEOUT signal.
        signals = manager._signal_bus.consume()
        assert len(signals) == 1
        assert signals[0].type == SignalType.ACTION_TIMEOUT
        assert signals[0].execution_id == specs[0].execution_id

    def test_mixed_batch_counts_correctly(self, monkeypatch, bootstrapped_registry):
        """A batch with success, failure, and timeout is counted correctly."""
        manager = QueryLoop(
            initial_query="test",
            loop_target="test",
            available_action_names=["calculate", "average_dog_weight"],
            registry=bootstrapped_registry,
        )

        call_count = [0]

        def fake_execute(name, args, context_provider, run_config):
            call_count[0] += 1
            if name == "calculate":
                return {"value": "4"}
            if name == "average_dog_weight":
                raise ValueError("No data")
            return {}

        monkeypatch.setattr(manager.query_action, "execute", fake_execute)

        specs = [
            ActionSpec(name="calculate", target="Sum", args={"expression": "2+2"}),
            ActionSpec(name="average_dog_weight", target="Weight", args={"breed": "labrador"}),
        ]
        outcome = manager._parallel_dispatcher.dispatch(
            specs, manager.query_context, turn=1, timeout=5.0
        )

        assert outcome.total == 2
        assert outcome.completed == 1
        assert outcome.failed == 1
        assert outcome.timed_out == 0

        signals = manager._signal_bus.consume()
        types = [s.type for s in signals]
        assert SignalType.ACTION_COMPLETED in types
        assert SignalType.ACTION_FAILED in types
