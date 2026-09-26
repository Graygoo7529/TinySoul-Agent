from datetime import date
from dataclasses import replace
from pathlib import Path
import sys
import pytest

from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.infra.model_services import ModelServices
from tinysoul.infra.model_services.config import ModelServicesSettings
from tinysoul.kernel.action.models import (
    ModelUseRegistry,
    ModelUseDescriptor,
    ModelUseBinding,
    ModelImplementation,
    ModelOperation,
)
from tinysoul.kernel.retrieval.contracts import RetrievalRequest, DirectorySource, SourceKind, OperationKind
from tinysoul.kernel.retrieval.policy import RetrievalPolicy
from tinysoul.kernel.retrieval.operations import SearchSession
from tinysoul.kernel.retrieval.selection import CandidateSelector
from functools import partial
from tests.support.model_uses import action_tasks
from tinysoul.kernel.action.call import ActionCall
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.catalog.specs import (
    ActionDomainSpec,
    ActionSpec,
    ActionToolSpec,
    ActionSemanticSpec,
    ActionRuntimeSpec,
    ActionExecutionSpec,
)
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.execution.executor import ActionExecutionContext
from tinysoul.kernel.action.result import ActionResultStatus
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.llm.protocol.requests import TaskCall, ModelContextOverflowPolicy
from tinysoul.llm.protocol.responses import (
    TaskResult,
    RawResponse,
    JsonAnswer,
    TaskFailure,
    TaskFailureReason,
    TaskResultStatus,
)
from tinysoul.plugins.capabilities.expand.actions import ExpandAction, ExpandOperation
from tinysoul.plugins.capabilities.expand.config import (
    ExpandSettings,
    MCPServerSettings,
)
from tinysoul.plugins.capabilities.expand.engine import ExpandEngine
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.runtime import RunScope, RunLevel


class Selector:
    def __init__(self) -> None:
        self.calls: list[TaskCall] = []
        self.answer: JsonObject = {"ids": ["c0"]}
        self.overflow = False

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        if self.overflow:
            return TaskResult(
                status=TaskResultStatus.FAILURE,
                raw_response=None,
                answer=None,
                failure=TaskFailure(reason=TaskFailureReason.INPUT_CAPACITY),
            )
        return TaskResult.success(
            raw_response=RawResponse("{}", "selector", "test"),
            answer=JsonAnswer(self.answer),
            tool_calls=(),
        )


@pytest.mark.parametrize("inline_limit", [16000, 1400])
async def test_four_actions_share_exact_definitions_scope_and_bounded_selection(
    tmp_path: Path,
    inline_limit: int,
) -> None:
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine = ExpandEngine(
        ExpandSettings(
            page_size=1,
            max_inline_chars=inline_limit,
            servers=(
                MCPServerSettings(
                    "local",
                    enabled=True,
                    command=sys.executable,
                    args=(str(Path(__file__).with_name("fixture_server.py")),),
                ),
            ),
        ),
        root=tmp_path,
        workspace=workspace,
        environment={},
    )
    context = ContextEngineBuilder(system_text="Identity").build()
    context.begin_turn("Find arithmetic tools")
    await context.open_segments(date(2026, 9, 21))
    selector = Selector()
    runner = action_tasks(context)
    services = ModelServices(ModelServicesSettings(), env={})
    models = ModelUseRegistry(
        (
            ModelUseDescriptor(
                "expand.search.select", "expand.search", ModelOperation.SELECT
            ),
        ),
        (
            ModelUseBinding(
                "expand.search.select",
                ModelImplementation.LLM_TASK,
                task_profile="llm_action",
            ),
        ),
    )
    page_budget = max(2048, inline_limit)
    queries = SearchSession(
        action_id="expand.search",
        retrieval_policies=(RetrievalPolicy("expand.search", tuple(SourceKind), tuple(OperationKind), page_max_chars=page_budget),),
        source=partial(engine.search_corpus, page_budget=page_budget),
        selector=CandidateSelector(
            models=models, invoke=selector.run, services=services
        ),
    )

    async def invoke(operation: ExpandOperation, params: JsonObject):
        name = "expand." + operation.value
        spec = ActionSpec(
            name=name,
            domain="expand",
            tool=ActionToolSpec(
                name=name,
                description=name,
                schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            ),
            semantic=ActionSemanticSpec(),
            runtime=ActionRuntimeSpec(),
            execution=ActionExecutionSpec(executor=name),
        )
        execution = (
            ActionExecutionBuilder()
            .prepare_batch(
                (ActionCall("call", name, params, 1),),
                catalog=ActionCatalog(
                    domains=(ActionDomainSpec("expand", "MCP"),), actions=(spec,)
                ),
                scope=RunScope().push(RunLevel.PHASE, "phase3"),
                batch_id="batch",
            )
            .batch.executions[0]
        )
        if operation is ExpandOperation.SEARCH and "continuation" not in params:
            execution = replace(
                execution,
                call=replace(
                    execution.call,
                            params={
                                "source": (
                                    {
                                        "kind": "directory",
                                        "scope": "all",
                                    }
                                        if params.get("query") in {"both tools", "sum"}
                                    else {
                                        "kind": "query",
                                        "scope": "all",
                                        "query": params.get("query", ""),
                                    }
                                ),
                            "steps": [
                                {
                                    "op": "select",
                                    "criterion": "add two integers",
                                }
                            ],
                        },
                ),
            )
        return await ExpandAction(engine, operation, runner, queries).execute(
            execution, ActionExecutionContext()
        )

    try:
        listed = await invoke(ExpandOperation.DESCRIBE_SERVERS, {})
        assert listed.status is ActionResultStatus.SUCCESS and not selector.calls
        assert "inputSchema" not in str(listed.payload)
        assert listed.payload is not None
        assert isinstance(listed.payload["next_page"], str)
        second = await invoke(
            ExpandOperation.DESCRIBE_SERVERS, {"page": listed.payload["next_page"]}
        )
        assert second.payload and not second.payload["next_page"]
        stale = await invoke(
            ExpandOperation.DESCRIBE_TOOLS, {"page": listed.payload["next_page"]}
        )
        assert stale.status is ActionResultStatus.FAILED
        described = await invoke(
            ExpandOperation.DESCRIBE_TOOLS,
            {"tools": [{"server_id": "local", "tool_name": "add"}]},
        )
        assert "inputSchema" in str(described.payload)
        bounded = await engine.search_corpus(
            RetrievalRequest(DirectorySource("all")),
            page_budget=256,
        )
        assert all(item.attributes.get("describe") for item in bounded.candidates)
        assert {item.ref for item in bounded.candidates} == {
            "mcp:local/add",
            "mcp:local/long_text",
        }
        found = await invoke(
            ExpandOperation.SEARCH, {"query": "加法 / add two integers"}
        )
        assert found.status is ActionResultStatus.SUCCESS and "inputSchema" in str(
            found.payload
        )
        assert (
            len(selector.calls) == 1
            and selector.calls[0].context_overflow_policy
            is ModelContextOverflowPolicy.RETURN_FAILURE
        )
        assert any(
            message.label == "retrieval:selection"
            for message in selector.calls[0].messages.messages
        )
        result = await invoke(
            ExpandOperation.CALL,
            {"server_id": "local", "tool_name": "add", "arguments": {"a": 2, "b": 6}},
        )
        assert result.payload and result.payload["structured"] == {"value": 8}
        selector.answer = {"ids": ["c0", "c1"]}
        multiple = await invoke(ExpandOperation.SEARCH, {"query": "both tools"})
        assert multiple.status is ActionResultStatus.SUCCESS and multiple.payload
        assert len(dumps_json(multiple.payload)) <= page_budget
        items = multiple.payload["items"]
        assert isinstance(items, list)
        continuation = multiple.payload["continuation"]
        if continuation:
            assert isinstance(continuation, str)
            before = len(selector.calls)
            page = await invoke(ExpandOperation.SEARCH, {"continuation": continuation})
            more = page.payload["items"]
            assert isinstance(more, list)
            items += more
            assert len(selector.calls) == before
        assert len(items) == 2
        selector.answer = {"ids": ["invented"]}
        assert (
            await invoke(ExpandOperation.SEARCH, {"query": "sum"})
        ).status is ActionResultStatus.FAILED
        selector.overflow = True
        limited = await invoke(ExpandOperation.SEARCH, {"query": "sum"})
        assert limited.payload and limited.payload["scope_required"] is True
        filtered = await invoke(
            ExpandOperation.DESCRIBE_TOOLS, {"server_ids": ["disabled"]}
        )
        assert filtered.payload and filtered.payload["tools"] == []
        assert "unavailable" in str(filtered.payload)
    finally:
        await engine.close()
        await services.close()
