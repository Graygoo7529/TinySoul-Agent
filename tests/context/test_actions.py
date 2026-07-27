from pathlib import Path

from tinysoul.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionFramework,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.context import ContextEngineBuilder, build_trace_phase_note_signal
from tinysoul.context.actions import ContextInspectExecutor
from tinysoul.runtime import RunLevel, RunScope, SignalBus
from tinysoul.runtime.bridge import RuntimeContextBridge


def test_context_inspect_continuation_is_visible_only() -> None:
    context = (
        ContextEngineBuilder(system_text="test")
        .with_trace_heap(
            chunk_max_chars=12000,
            branch_factor=4,
            min_hot_entries=0,
        )
        .with_trace_inspect_max_chars(1024)
        .build()
    )
    turn_id = context.begin_turn("inspect")
    scope = RunScope().push(RunLevel.TURN, turn_id)
    bus = SignalBus()
    bus.emit(
        build_trace_phase_note_signal(
            {"content": "x" * 3000},
            scope=scope,
            source="test",
            cycle_id="cycle_1",
        )
    )
    context.consume_signals(bus)
    context.compress()
    nodes = context.inspect_trace(f"turn:trace@{turn_id}")["nodes"]
    assert isinstance(nodes, list)
    root = nodes[0]
    assert isinstance(root, dict)
    ref = root["ref"]
    assert isinstance(ref, str)

    action = ActionCatalogLoader().load(Path("tinysoul/action/catalog")).get_action(
        "core.context.inspect"
    )
    result = ContextInspectExecutor(
        context,
        runtime_bridge=RuntimeContextBridge(),
    ).execute(
        ActionExecution(
            action=action,
            call=ActionCall(
                call_id="call_context_inspect",
                action_name=action.name,
                params={"ref": ref},
                sequence=1,
            ),
            framework=ActionFramework(
                invoke_id="invoke_context_inspect",
                batch_id="batch_context_inspect",
                scope=scope,
                domain="core",
            ),
        ),
        ActionExecutionContext(),
    )

    assert "next_continuation" in result.payload
    assert result.trace_projection is not None
    assert "next_continuation" not in result.trace_projection.canonical_payload
