"""Explicit ACP connection and delegation actions; Job controls remain in core."""

from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.infra.process import ManagedProcessCloseError
from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionResult,
    ActionLocalFailure,
    ActionFailureDisposition,
    ActionResultStage,
)
from tinysoul.kernel.jobs import JobError, JobRequestError
from tinysoul.kernel.jobs.runtime_bridge import RuntimeJobsBridge
from tinysoul.plugins.workspace import WorkspaceError, WorkspaceContractError
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from .engine import SubagentEngine
from .failures import SubagentFailure, SubagentRequestError
from .runtime_bridge import RuntimeSubagentBridge


class SubagentOperation(StrEnum):
    AGENTS = "agents"
    CONNECT = "connect"
    DELEGATE = "delegate"
    RESPOND = "respond"
    COLLECT = "collect"
    DISCONNECT = "disconnect"


class SubagentAction:
    def __init__(
        self, engine: SubagentEngine, operation: SubagentOperation, scenario: str
    ) -> None:
        self._engine, self._operation, self._scenario = engine, operation, scenario

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        try:
            payload = await self._execute(execution, context)
        except (SubagentRequestError, JobRequestError, WorkspaceContractError) as exc:
            return ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                stage=ActionResultStage.EXECUTE,
                failure=ActionLocalFailure(
                    reason=exc.reason.value
                    if isinstance(exc, SubagentRequestError)
                    else "invalid_request",
                    scope="subagent.action",
                    disposition=ActionFailureDisposition.CHANGE_REQUEST,
                    feedback=str(exc)
                    if isinstance(exc, SubagentRequestError)
                    else "The requested resource is unavailable in this Turn.",
                ),
            )
        except JobError as exc:
            raise RuntimeJobsBridge().from_error(exc) from exc
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        except ManagedProcessCloseError as exc:
            raise RuntimeSubagentBridge().close_failed(exc) from exc
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=payload,
        )

    async def _execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> JsonObject:
        params, turn_id, engine = (
            execution.call.params,
            execution.framework.turn_id,
            self._engine,
        )

        def text(key: str, default: str | None = None) -> str:
            value = params.get(key, default)
            if not isinstance(value, str):
                raise SubagentRequestError(
                    SubagentFailure.INVALID_REQUEST,
                    "Required action text or identity is absent.",
                )
            return value

        match self._operation:
            case SubagentOperation.AGENTS:
                return engine.agents()
            case SubagentOperation.CONNECT:
                return await engine.connect(
                    turn_id, self._scenario, text("agent_id"), text("cwd_link", "")
                )
            case SubagentOperation.DELEGATE:
                links = params.get("reference_links", [])
                if (
                    not isinstance(links, list)
                    or len(links) > 8
                    or any(not isinstance(link, str) for link in links)
                ):
                    raise SubagentRequestError(
                        SubagentFailure.INVALID_REQUEST,
                        "Reference links must be a bounded list.",
                    )
                brief = await engine.prepare_brief(
                    text("brief"),
                    tuple(link for link in links if isinstance(link, str)),
                    context.owner_operations,
                )
                job_id = await engine.delegate(turn_id, text("connection_id"), brief)
                return {"job_id": job_id, "connection_id": text("connection_id")}
            case SubagentOperation.RESPOND:
                engine.backend(turn_id, text("job_id")).respond(
                    text("request_id"), text("option_id")
                )
                return {
                    "job_id": text("job_id"),
                    "request_id": text("request_id"),
                    "accepted": True,
                }
            case SubagentOperation.COLLECT:
                cursor = params.get("cursor", 0)
                if type(cursor) is not int:
                    raise SubagentRequestError(
                        SubagentFailure.INVALID_REQUEST,
                        "Collection cursor must be an integer.",
                    )
                return await engine.backend(turn_id, text("job_id")).collect(cursor)
            case SubagentOperation.DISCONNECT:
                await engine.disconnect(turn_id, text("connection_id"))
                return {"connection_id": text("connection_id"), "disconnected": True}


def register_subagent_actions(
    builder: ActionEngineBuilder, *, engine: SubagentEngine, scenario: str
) -> ActionEngineBuilder:
    for operation in SubagentOperation:
        identity = f"subagent.{operation.value}"
        if engine.available:
            builder.register_executor(
                identity, SubagentAction(engine, operation, scenario)
            )
        else:
            builder.mark_actions_unsupported(identity)
    return builder
