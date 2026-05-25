"""
Monitor Action — experimental ONGOING action.

Launches a background daemon thread that emits ONGOING_TICK signals
at a configurable interval. Demonstrates the ONGOING action lifecycle:

  execute() → ONGOING_STARTED → [ONGOING_TICK ...] → ONGOING_COMPLETED

The background thread uses context_provider.emit_signal() to report
results without direct state mutation.
"""
from __future__ import annotations

import json

import threading
import time
from typing import Any

from tinysoul.action.framework.executor import ActionExecutor
from tinysoul.action.framework.handler import ActionBase
from tinysoul.action.framework.run_config import RunConfig, TerminationReason
from tinysoul.context.ongoing import OngoingControl
from tinysoul.trap.signal import Signal, SignalType
from tinysoul.context.protocols import ContextProvider


ACTION_SPEC_MONITOR = {
    "name": "monitor",
    "description": "Start a background monitor that periodically reports status via ONGOING ticks",
    "cluster": {
        "type": "NATIVE",
        "domain": "MONITOR",
    },
    "profile": {
        "action_intention": "EXTERNAL_PROBING",
        "action_environment_effect": "READ_ONLY",
        "action_mode": "ONGOING",
        "llm_dependency": "NONE",
    },
    "contract": {
        "applicability": {
            "mode": "CONDITIONAL",
            "conditions": [
                "need to observe a value over time",
            ],
        },
        "preconditions": [],
        "postconditions": {
            "logical_state_effects": [
                "Adds action_name to ongoing_action_list",
                "Produces multiple ONGOING_TICK action records over time",
            ],
            "physical_environment_effects": [],
        },
    },
    "detail": {
        "parameter_schema": {
            "type": "object",
            "properties": {
                "interval": {
                    "type": "number",
                    "description": "Seconds between ticks (default 2.0)",
                },
                "max_ticks": {
                    "type": "integer",
                    "description": "Maximum number of ticks before auto-stop (default 3)",
                },
            },
            "required": [],
        },
        "examples": [
            {
                "interval": 2.0,
                "max_ticks": 3,
            },
        ],
        "edge_case_handling": [
            "If interval <= 0, defaults to 2.0",
            "If max_ticks <= 0, defaults to 3",
        ],
    },
}

ACTION_JSON_MONITOR = json.dumps(ACTION_SPEC_MONITOR, ensure_ascii=False, indent=2)


class MonitorExecutor(ActionExecutor):
    """Executor that starts a background daemon thread for periodic ticks."""

    def execute(
        self,
        action_input: dict,
        context_provider: ContextProvider | None,
        run_config: RunConfig,
    ) -> dict:
        if context_provider is None:
            raise RuntimeError("monitor requires a ContextProvider")
        run_config.raise_if_terminated()

        interval = float(action_input.get("interval", 2.0))
        max_ticks = int(action_input.get("max_ticks", 3))

        if interval <= 0:
            interval = 2.0
        if max_ticks <= 0:
            max_ticks = 3

        turn = getattr(context_provider, "current_turn", 0)
        execution_id = run_config.execution_id
        control = OngoingControl(
            execution_id=execution_id,
            action_name="monitor",
        )
        registrar = getattr(context_provider, "register_ongoing_control", None)
        if callable(registrar):
            registrar(control)

        def _background() -> None:
            completed_payload = {
                "status": "completed",
                "total_ticks": 0,
            }
            for tick in range(1, max_ticks + 1):
                if control.terminate_event.wait(interval):
                    completed_payload = {
                        "status": "terminated",
                        "reason": (
                            control.termination_reason.value
                            if control.termination_reason
                            else TerminationReason.USER_CANCEL.value
                        ),
                        "total_ticks": tick - 1,
                    }
                    break
                context_provider.emit_signal(
                    Signal(
                        type=SignalType.ONGOING_TICK,
                        turn=turn,
                        step="execute_action",
                        action_name="monitor",
                        action_input=action_input,
                        execution_id=execution_id,
                        payload={
                            "result": {
                                "tick": tick,
                                "max_ticks": max_ticks,
                                "elapsed": tick * interval,
                            }
                        },
                    )
                )
                completed_payload = {
                    "status": "completed",
                    "total_ticks": tick,
                }

            unregister = getattr(context_provider, "unregister_ongoing_control", None)
            if callable(unregister):
                unregister(execution_id)

            context_provider.emit_signal(
                Signal(
                    type=SignalType.ONGOING_COMPLETED,
                    turn=turn,
                    step="execute_action",
                    action_name="monitor",
                    action_input=action_input,
                    execution_id=execution_id,
                    payload={"result": completed_payload},
                )
            )

        # Daemon thread: dies with the main process; short-lived for demo
        threading.Thread(target=_background, daemon=True).start()

        return {
            "status": "ongoing_started",
            "message": f"Monitor started (interval={interval}s, max_ticks={max_ticks})",
        }


class MonitorAction(ActionBase):
    """ONGOING action that periodically emits ticks from a background thread."""

    action_name = "monitor"
    ACTION_JSON = ACTION_JSON_MONITOR
    _executor = MonitorExecutor()


def register_to(registry):
    """Register monitor action to the given registry."""
    from tinysoul.action.framework.registry import ActionRegistry

    if isinstance(registry, ActionRegistry):
        registry.register_action_class(MonitorAction)
