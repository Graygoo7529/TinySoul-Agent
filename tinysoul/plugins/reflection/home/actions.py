"""Home Reflection diff/review over the Home owner's effective copies."""

from __future__ import annotations

from dataclasses import replace

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.action import (
    ActionEngineBuilder, ActionExecution, ActionExecutionContext,
    ActionResult, ActionResultStage, ActionLocalFailure,
    ActionFailureDisposition, ActionExecutor,
)
from tinysoul.plugins.home import HomeReviewChange, HomeReviewResolution
from tinysoul.plugins.home.services import HomeReviewService
from tinysoul.plugins.home.errors import AgentHomeContractError, AgentHomeError
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.plugins.home.background import HOME_CONTEXT_UPDATE
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import Signal

HOME_MAINTENANCE_ACTIONS = ("home_reflection.diff", "home_reflection.review")


class HomeReflectionActionController(ActionExecutor):
    """Expose selected review operations without a separate task state machine."""

    def __init__(self, home: HomeReviewService) -> None:
        self._home = home

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext,
    ) -> ActionResult:
        # A bounded review finishes its selected owner commits and records them
        # before the Action runner propagates cancellation.
        return await context.owner_operations.run_async(lambda: self._review(
            execution, replace(context, owner_operations=JoinedOperations()),
        ))

    async def _review(
        self, execution: ActionExecution, context: ActionExecutionContext,
    ) -> ActionResult:
        home = self._home.using(context.owner_operations)
        params = execution.call.params
        raw_paths = params.get("paths", [])
        if not isinstance(raw_paths, list) or any(
            not isinstance(path, str) or not path for path in raw_paths
        ):
            return _failed(execution, "paths must contain Home Links")
        paths = tuple(dict.fromkeys(str(path) for path in raw_paths))
        try:
            snapshot = await home.review_snapshot()
            if execution.call.action_name == "home_reflection.diff":
                selected = tuple(
                    review for review in snapshot.reviews if not paths or review.link in paths
                )
                payload: JsonObject = {
                    "items": [
                        review.to_review_json() if paths else {
                            "link": review.link,
                            "kind": "change" if isinstance(review, HomeReviewChange) else "skill_review",
                        }
                        for review in selected
                    ],
                }
            else:
                bus = context.require_signal_bus()
                decision = params.get("decision")
                if not paths or decision not in {"accept", "reject"}:
                    return _failed(execution, "Select Home Links and accept or reject")
                resolution = HomeReviewResolution(str(decision))
                results: list[JsonObject] = []
                for path in paths:
                    reviews = tuple(review for review in snapshot.reviews if review.link == path)
                    if not reviews:
                        results.append({"link": path, "reviewed": False, "reason": "no_pending_change"})
                        continue
                    changes = tuple(review for review in reviews if isinstance(review, HomeReviewChange))
                    if resolution is HomeReviewResolution.ACCEPT and not changes:
                        results.append({
                            "link": path, "reviewed": False,
                            "reason": "edit_effective_skill_before_accepting",
                        })
                        continue
                    for review in reviews:
                        if not isinstance(review, HomeReviewChange):
                            current = tuple(
                                item for item in (await home.review_snapshot()).reviews
                                if item.link == path and not isinstance(item, HomeReviewChange)
                            )
                            if not current:
                                continue
                            review = current[0]
                        await home.resolve_review(
                            review.token,
                            resolution if isinstance(review, HomeReviewChange) else HomeReviewResolution.REJECT,
                        )
                    results.append({"link": path, "reviewed": True, "decision": decision})
                payload = to_json_object({"items": results})
                bus.emit(Signal(
                    name=HOME_CONTEXT_UPDATE, source="home_reflection.review",
                    scope=execution.framework.scope, payload={"refresh": True},
                ))
        except AgentHomeContractError:
            return _failed(execution, "Home review request is invalid; inspect the current diff")
        except AgentHomeError as exc:
            raise RuntimeAgentHomeBridge().from_home_error(exc) from exc
        return ActionResult.success(
            call_id=execution.call.call_id, invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id, action_name=execution.call.action_name,
            sequence=execution.call.sequence, domain=execution.framework.domain,
            payload=payload,
        )


def register_home_maintenance_actions(
    builder: ActionEngineBuilder, *, controller: HomeReflectionActionController,
) -> ActionEngineBuilder:
    for handler in HOME_MAINTENANCE_ACTIONS:
        builder.register_executor(handler, controller)
    return builder


def _failed(execution: ActionExecution, feedback: str) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id, invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id, action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE, sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason="invalid_review", scope="home.reflection",
            disposition=ActionFailureDisposition.CHANGE_REQUEST, feedback=feedback,
        ),
    )
