from __future__ import annotations
from tests.support.actions import packaged_catalog
from tests.support.actions import sample_catalog
from tinysoul.plugins.workspace.services import WorkspaceService
from collections import deque
from dataclasses import dataclass, field
from tinysoul.kernel.action import ActionEngine
from tests.support.model_uses import action_tasks
from tinysoul.kernel.context import ContextEngine
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.messages import MessageStack, TextPart
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import (
    JsonAnswer,
    RawResponse,
    TaskFailure,
    TaskResult,
)
from tinysoul.llm.protocol.tools import ToolCallRecord
from tinysoul.plugins.memory.services import MemoryService
from tinysoul.plugins.memory import MemoryEngine, register_memory_actions
from tinysoul.runtime import SignalBus, ObservationEvent, ObservationLevel
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.plugins.workspace import WorkspaceEngine, register_workspace_actions
from tests.support.actions import FunctionActionEngineBuilder


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@dataclass
class RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


def _action_engine(
    *,
    memory: MemoryEngine | None = None,
    workspace: WorkspaceEngine | None = None,
    workspace_context: ContextEngine | None = None,
    workspace_bus: SignalBus | None = None,
    workspace_llm: FakeLLM | None = None,
) -> ActionEngine:
    catalog = (
        packaged_catalog()
        if workspace is not None or memory is not None
        else sample_catalog()
    )
    if workspace is not None or memory is not None:
        domains = ({"workspace"} if workspace is not None else set()) | (
            {"memory"} if memory is not None else set()
        )
        names = {
            "core.answer",
            "core.reason",
            "core.context.inspect",
            "home.inspect",
            "workspace.list",
        }
        catalog = catalog.with_actions(
            action.name
            for action in catalog.actions()
            if action.domain in domains or action.name in names
        )
    builder = (
        FunctionActionEngineBuilder(catalog)
        .register_function("core.answer", lambda execution, context: {"text": "done"})
        .register_function("core.reason", lambda execution, context: {"ok": True})
        .register_function("home.inspect", lambda execution, context: {"read": True})
        .register_function(
            "core.context.inspect",
            lambda execution, context: {},
            executor_id="context.inspect",
        )
    )
    if workspace is None:
        builder.register_function(
            "workspace.list", lambda execution, context: {"scanned": True}
        )
    else:
        if workspace_context is None or workspace_bus is None or workspace_llm is None:
            raise AssertionError(
                "Real Workspace actions require Context, SignalBus, and LLM"
            )
        from tinysoul.infra.references import ReferenceResolver
        from tinysoul.kernel.retrieval.operations import SearchSession
        from tinysoul.kernel.retrieval.policy import RetrievalPolicy
        from tinysoul.kernel.retrieval.contracts import OperationKind, SourceKind

        async def workspace_source(request):
            return workspace.retrieval_corpus(request, references=ReferenceResolver())

        workspace_queries = SearchSession(
            action_id="workspace.search",
            retrieval_policies=(
                RetrievalPolicy(
                    "workspace.search", tuple(SourceKind), tuple(OperationKind)
                ),
            ),
            source=workspace_source,
        )
        register_workspace_actions(
            builder,
            workspace=WorkspaceService(workspace, queries=workspace_queries),
            tasks=action_tasks(workspace_context),
            llm=workspace_llm,
        )
    if memory is not None:
        from tinysoul.infra.references import ReferenceResolver
        from tinysoul.kernel.retrieval.operations import SearchSession
        from tinysoul.kernel.retrieval.policy import RetrievalPolicy
        from tinysoul.kernel.retrieval.contracts import SourceKind

        async def source(request):
            return memory.search_corpus(request, references=ReferenceResolver())

        queries = SearchSession(
            action_id="memory.search",
            retrieval_policies=(
                RetrievalPolicy("memory.search", (SourceKind.QUERY,), ()),
            ),
            source=source,
        )
        register_memory_actions(
            builder,
            memory=MemoryService(memory, queries=queries),
            runtime_bridge=RuntimeMemoryBridge(),
        )
    return builder.build()


def _tool_result(*tool_calls: ToolCallRecord) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
            tool_calls=tool_calls,
        ),
        answer=None,
        tool_calls=tool_calls,
    )


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _task_failure(feedback: str) -> TaskResult:
    return TaskResult.failure_result(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
        ),
        failure=TaskFailure(model_feedback=feedback),
    )


def _message_stack_text(stack: MessageStack) -> str:
    return "\n".join(
        part.text
        for message in stack.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )


def _stack() -> MessageStack:
    return MessageStack()
