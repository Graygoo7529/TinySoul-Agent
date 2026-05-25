"""
State update application for Query Loop Step 3.

Provides a pure function `apply_state_updates` that applies LLM-generated
semantic updates (todo operations, milestone additions) to a QueryState
instance.  This keeps QueryLoop focused on orchestration while making the
state-mutation logic independently testable without constructing a full
QueryLoop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tinysoul.infra import EventLogger
    from .state import QueryState


def apply_state_updates(
    query_state: QueryState,
    updates: dict[str, Any],
    turn: int,
    logger: EventLogger | None = None,
) -> None:
    """
    Apply LLM-generated state updates to *query_state*.

    Processes ``todo_operations`` (add / complete / cancel) and
    ``milestone_operation`` (add / no-change).  Each operation is executed
    inside its own ``try/except`` so that a single failing operation does
    not discard the others.  Failures are recorded as loop errors.

    Args:
        query_state: The runtime state facade to mutate.
        updates: Dict shaped like
            ``{"todo_operations": [...], "milestone_operation": "...", "milestone_param": "..."}``.
        turn: Current turn number (1-based) for error attribution.
        logger: Optional structured event logger for todo/milestone events.
    """
    for todo_op in updates.get("todo_operations", []):
        op = todo_op.get("operation")
        key = todo_op.get("key")
        desc = todo_op.get("description")

        try:
            if op == "add" and desc:
                query_state.add_todo(description=desc, todo_id=key)
                if logger is not None:
                    logger.todo_added(key=key, desc=desc)
            elif op == "complete" and key:
                completed = query_state.complete_todo(key)
                if completed and logger is not None:
                    logger.todo_completed(key=key, desc=completed.description)
            elif op == "cancel" and key:
                cancelled = query_state.cancel_todo(key)
                if cancelled and logger is not None:
                    logger.todo_cancelled(key=key, desc=cancelled.description)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            from tinysoul.trap import TinysoulError

            error_type = (
                type(e).__name__
                if isinstance(e, TinysoulError)
                else f"state/{type(e).__name__}"
            )
            query_state.add_loop_error(
                turn=turn,
                step="update_state",
                error_type=error_type,
                message=f"Todo operation '{op}' failed for key '{key}': {str(e)}",
            )

    try:
        milestone_op = updates.get("milestone_operation", "no-change")
        milestone_param = updates.get("milestone_param")

        if milestone_op == "add" and milestone_param:
            query_state.add_milestone(milestone_param)
            if logger is not None:
                logger.milestone_added(text=milestone_param)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        from tinysoul.trap import TinysoulError

        error_type = (
            type(e).__name__
            if isinstance(e, TinysoulError)
            else f"state/{type(e).__name__}"
        )
        query_state.add_loop_error(
            turn=turn,
            step="update_state",
            error_type=error_type,
            message=str(e),
        )
