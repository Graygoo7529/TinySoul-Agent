"""Action call and execution input models."""

from __future__ import annotations

from uuid import uuid4

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RunScope

from ..catalog.catalog import ActionCatalog
from ..errors import ActionContractError, ActionInvariantError
from tinysoul.runtime import CyclePhase
from ..result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionPhaseResult,
    ActionPhaseResultStage,
    ActionResult,
    ActionResultStage,
)


from ..call import (
    ActionCall,
    ActionExecution,
    ActionBatch,
    ActionFramework,
    ActionBatchPreparation,
)


class ActionExecutionBuilder:
    """Build execution inputs from normalized action calls."""

    def prepare_batch(
        self,
        calls: tuple[ActionCall, ...],
        *,
        catalog: ActionCatalog,
        scope: RunScope,
        batch_id: str | None = None,
        turn_id: str = "",
        cycle_id: str = "",
        phase: CyclePhase = CyclePhase.PHASE3,
    ) -> ActionBatchPreparation:
        resolved_batch_id = batch_id or f"action_batch_{uuid4().hex[:8]}"
        executions: list[ActionExecution] = []
        results: list[ActionResult] = []
        seen_call_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for call in calls:
            if call.call_id in seen_call_ids:
                results.append(
                    _prepare_failure(
                        call,
                        batch_id=resolved_batch_id,
                        feedback=f"Duplicate action call id: {call.call_id}",
                        reason="duplicate_call_id",
                    )
                )
                continue
            if call.sequence in seen_sequences:
                results.append(
                    _prepare_failure(
                        call,
                        batch_id=resolved_batch_id,
                        feedback=f"Duplicate action sequence: {call.sequence}",
                        reason="duplicate_sequence",
                    )
                )
                continue
            seen_call_ids.add(call.call_id)
            seen_sequences.add(call.sequence)
            if not catalog.has_action(call.action_name):
                results.append(
                    _prepare_failure(
                        call,
                        batch_id=resolved_batch_id,
                        feedback=f"Unknown action during preparation: {call.action_name}",
                        reason="unknown_action",
                    )
                )
                continue
            action = catalog.get_action(call.action_name)
            timeout = action.runtime.timeout_seconds
            executions.append(
                ActionExecution(
                    action=action,
                    call=call,
                    framework=ActionFramework(
                        invoke_id=f"action_invoke_{uuid4().hex[:8]}",
                        batch_id=resolved_batch_id,
                        scope=scope,
                        domain=action.domain,
                        timeout_seconds=timeout,
                        turn_id=turn_id,
                        cycle_id=cycle_id,
                        phase=phase,
                    ),
                )
            )
        try:
            batch = ActionBatch(
                batch_id=resolved_batch_id,
                executions=tuple(executions),
            )
        except ActionInvariantError as exc:
            return ActionBatchPreparation(
                batch=ActionBatch(batch_id=resolved_batch_id),
                results=tuple(results),
                phase_results=(
                    ActionPhaseResult.failed(
                        phase=phase,
                        stage=ActionPhaseResultStage.PREPARE,
                        failure=ActionLocalFailure(
                            reason="batch_invariant_error",
                            scope="action.prepare",
                            disposition=ActionFailureDisposition.STOP,
                            feedback="Action batch preparation failed.",
                        ),
                        frame_data={
                            "error_type": type(exc).__name__,
                        },
                        turn_id=turn_id,
                        cycle_id=cycle_id,
                    ),
                ),
            )
        return ActionBatchPreparation(
            batch=batch,
            results=tuple(results),
        )

    def build_batch(
        self,
        calls: tuple[ActionCall, ...],
        *,
        catalog: ActionCatalog,
        scope: RunScope,
        batch_id: str | None = None,
        turn_id: str = "",
        cycle_id: str = "",
        phase: CyclePhase = CyclePhase.PHASE3,
    ) -> ActionBatch:
        preparation = self.prepare_batch(
            calls,
            catalog=catalog,
            scope=scope,
            batch_id=batch_id,
            turn_id=turn_id,
            cycle_id=cycle_id,
            phase=phase,
        )
        if preparation.results or preparation.phase_results:
            raise ActionContractError("Action batch preparation produced local results")
        return preparation.batch


def _prepare_failure(
    call: ActionCall,
    *,
    batch_id: str,
    feedback: str,
    reason: str,
    frame_data: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=call.call_id,
        batch_id=batch_id,
        action_name=call.action_name,
        stage=ActionResultStage.PREPARE,
        sequence=call.sequence,
        failure=ActionLocalFailure(
            reason=reason,
            scope="action.prepare",
            disposition=ActionFailureDisposition.STOP,
            feedback=feedback,
        ),
        frame_data=frame_data,
    )
