"""Four finite actions over the MCP owner and the existing LLM task path."""

from enum import StrEnum

from tinysoul.infra.json import JsonObject, JsonValue, dumps_json
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
from tinysoul.kernel.action.tasks import ActionTaskFactory
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.contracts import (
    SearchFailure,
    SearchContext,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.requests import parse_search_request
from tinysoul.plugins.workspace import WorkspaceError
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from .engine import ExpandEngine
from .failures import ExpandFailure, ExpandRequestError
from .runtime_bridge import RuntimeExpandBridge


class ExpandOperation(StrEnum):
    DESCRIBE_SERVERS = "describe_servers"
    DESCRIBE_TOOLS = "describe_tools"
    SEARCH = "search"
    CALL = "call"


class ExpandAction:
    def __init__(
        self,
        engine: ExpandEngine,
        operation: ExpandOperation,
        tasks: ActionTaskFactory,
        queries: SearchSession | None = None,
    ) -> None:
        self._engine, self._operation, self._queries = engine, operation, queries
        self._tasks = tasks

    async def execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> ActionResult:
        try:
            result = await self._execute(execution, context)
            if isinstance(result, ActionResult):
                return result
        except SearchFailure as exc:
            return _failure(
                execution,
                ExpandRequestError(
                    ExpandFailure.SELECTION
                    if exc.kind is SearchFailureKind.SELECTION_FAILED
                    else ExpandFailure.INVALID_REQUEST,
                    str(exc),
                ),
                payload={
                    "reason": exc.kind.value,
                    "scope_required": exc.kind is SearchFailureKind.SCOPE_REQUIRED,
                },
            )
        except ExpandRequestError as exc:
            return _failure(execution, exc)
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        except ManagedProcessCloseError as exc:
            raise RuntimeExpandBridge().close_failed(exc) from exc
        if result.get("is_error"):
            return _failure(
                execution,
                ExpandRequestError(
                    ExpandFailure.REMOTE, "Remote tool reported a failure."
                ),
                payload=result,
            )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=result,
        )

    async def _execute(
        self, execution: ActionExecution, context: ActionExecutionContext
    ) -> JsonObject | ActionResult:
        params, engine = execution.call.params, self._engine
        if self._operation is ExpandOperation.CALL:
            server, name, arguments = (
                params.get("server_id"),
                params.get("tool_name"),
                params.get("arguments", {}),
            )
            if (
                not isinstance(server, str)
                or not isinstance(name, str)
                or not isinstance(arguments, dict)
            ):
                raise ExpandRequestError(
                    ExpandFailure.INVALID_REQUEST,
                    "Provide a server, tool name and argument object.",
                )
            return await engine.call(
                server, name, arguments, operations=context.owner_operations
            )
        if self._operation is ExpandOperation.SEARCH:
            if self._queries is None:
                raise ExpandRequestError(
                    ExpandFailure.INVALID_REQUEST, "Tool search is not configured"
                )
            request = parse_search_request(
                params, self._queries.policies, directory_seed=True
            )
            if isinstance(request, str):
                return (await self._queries.search(request)).to_json()
            inputs = await self._tasks.selection_input(
                execution,
                include_context=request.options.context is SearchContext.CURRENT,
                control=context.control,
            )
            return (await self._queries.search(request, inputs=inputs)).to_json()
        cursor = params.get("page")
        if cursor is not None:
            if self._operation is ExpandOperation.SEARCH or not isinstance(cursor, str):
                raise ExpandRequestError(
                    ExpandFailure.INVALID_REQUEST, "Page identity is invalid."
                )
            return engine.page(cursor=cursor, kind=self._operation.value)
        server_ids = _server_ids(params.get("server_ids"))
        requested: tuple[tuple[str, str], ...] | None = None
        if self._operation is ExpandOperation.DESCRIBE_TOOLS:
            if (params.get("tools") is None) == (server_ids is None):
                raise ExpandRequestError(
                    ExpandFailure.INVALID_REQUEST,
                    "Provide tools or server_ids, exactly one selector.",
                )
            if params.get("tools") is not None:
                requested = _tool_ids(params["tools"])
                server_ids = tuple(dict.fromkeys(server for server, _ in requested))
        discovered = await engine.discover(server_ids)
        if self._operation is ExpandOperation.DESCRIBE_SERVERS:
            return engine.page(
                tuple(item.summary() for item in discovered.tools),
                servers=discovered.servers,
                kind=self._operation.value,
            )
        if self._operation is ExpandOperation.DESCRIBE_TOOLS:
            by_id = {(item.server_id, item.name): item for item in discovered.tools}
            items = (
                tuple(item.describe() for item in discovered.tools)
                if requested is None
                else tuple(
                    by_id[key].describe()
                    if key in by_id
                    else {
                        "server_id": key[0],
                        "tool_name": key[1],
                        "unavailable": "not_found",
                    }
                    for key in requested
                )
            )
            return engine.page(
                items, servers=discovered.servers, kind=self._operation.value
            )
        raise ExpandRequestError(
            ExpandFailure.INVALID_REQUEST, "Unsupported directory operation"
        )


def register_expand_actions(
    builder: ActionEngineBuilder,
    *,
    engine: ExpandEngine,
    tasks: ActionTaskFactory,
    queries: SearchSession | None = None,
) -> ActionEngineBuilder:
    for operation in ExpandOperation:
        identity = f"expand.{operation.value}"
        if engine.available:
            builder.register_executor(
                identity, ExpandAction(engine, operation, tasks, queries)
            )
        else:
            builder.mark_actions_unsupported(identity)
    return builder


def _server_ids(value: JsonValue | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 64
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ExpandRequestError(
            ExpandFailure.INVALID_REQUEST,
            "server_ids must be a non-empty bounded list.",
        )
    return tuple(item for item in value if isinstance(item, str))


def _tool_ids(value: JsonValue) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ExpandRequestError(
            ExpandFailure.INVALID_REQUEST,
            "tools must contain bounded structured identities.",
        )
    result: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("server_id"), str)
            or not isinstance(item.get("tool_name"), str)
        ):
            raise ExpandRequestError(
                ExpandFailure.INVALID_REQUEST,
                "Each tool requires server_id and tool_name.",
            )
        result.append((str(item["server_id"]), str(item["tool_name"])))
    return tuple(dict.fromkeys(result))


def _failure(
    execution: ActionExecution,
    error: ExpandRequestError,
    *,
    payload: JsonObject | None = None,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        stage=ActionResultStage.EXECUTE,
        payload=payload,
        failure=ActionLocalFailure(
            reason=error.reason.value,
            scope="expand.action",
            disposition=ActionFailureDisposition.CHANGE_REQUEST,
            feedback=str(error),
        ),
    )
