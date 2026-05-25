"""Tests for ErrorTrap control flow signal routing."""

from __future__ import annotations

import pytest

from tinysoul.trap.signal import Signal, SignalType
from tinysoul.trap.trap import Disposition, ErrorTrap


class TestControlFlowRouting:
    def test_loop_terminate_maps_to_complete_loop(self):
        trap = ErrorTrap()
        signal = Signal(
            type=SignalType.LOOP_COMPLETE,
            turn=1,
            step="execute_action",
            payload={},
        )
        outcome = trap.route(signal)
        assert outcome.decision == Disposition.COMPLETE_LOOP

    def test_loop_skip_step3_maps_to_next_turn(self):
        trap = ErrorTrap()
        signal = Signal(
            type=SignalType.LOOP_NEXT_TURN,
            turn=1,
            step="execute_action",
            payload={},
        )
        outcome = trap.route(signal)
        assert outcome.decision == Disposition.NEXT_TURN

    def test_loop_suspend_maps_to_suspend_loop(self):
        trap = ErrorTrap()
        signal = Signal(
            type=SignalType.LOOP_SUSPEND,
            turn=1,
            step="execute_action",
            payload={},
        )
        outcome = trap.route(signal)
        assert outcome.decision == Disposition.SUSPEND_LOOP

    def test_control_flow_takes_priority_over_success_signals(self):
        """Even if LOOP_COMPLETE were in _SUCCESS_SIGNALS (it's not),
        _CONTROL_FLOW should be checked first."""
        trap = ErrorTrap()
        # ACTION_COMPLETED should be NEXT_STEP
        completed = Signal(
            type=SignalType.ACTION_COMPLETED,
            turn=1,
            step="execute_action",
            payload={"result": {"status": "ok"}},
        )
        outcome = trap.route(completed)
        assert outcome.decision == Disposition.NEXT_STEP

        # LOOP_COMPLETE should be COMPLETE_LOOP
        terminate = Signal(
            type=SignalType.LOOP_COMPLETE,
            turn=1,
            step="execute_action",
            payload={},
        )
        outcome = trap.route(terminate)
        assert outcome.decision == Disposition.COMPLETE_LOOP
