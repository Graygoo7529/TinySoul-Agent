from __future__ import annotations
import asyncio
import sys
from pathlib import Path
import httpx
import pytest
from tinysoul.agent import UserTurnRequest
from tinysoul.gateway.endpoint import EndpointEngine
from tinysoul.gateway.endpoint.http import create_endpoint_app
from tinysoul.infra.config import ConfigMutation
from tinysoul.infra.references import ReferenceError
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.context.errors import ContextContractError, ContextInvariantError
from tinysoul.llm.protocol.responses import RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.workspace.services import WorkspaceService
from tests.agent.support import (
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


async def test_v2_turn_admission_question_budget_and_result_share_sdk_owner(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_question",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "ask",
                "core.ask",
                {
                    "question": "Choose a direction",
                    "options": [
                        {
                            "id": "a",
                            "label": "Execute",
                            "description": "Use the approved plan",
                        }
                    ],
                },
                ToolKind.ACTION,
            ),
        )
    ):
        llm.results.appendleft(
            TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None,
                tool_calls=(call,),
            )
        )
    endpoints: list[EndpointEngine] = []
    agent = await _create(tmp_path, llm, endpoints=endpoints, max_cycles=1)
    await agent.start()
    app = create_endpoint_app(endpoints[0], endpoints[0].settings)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {'x' * 32}"},
        ) as client:
            response = await client.post(
                "/v2/requests",
                json={"text": "/reply literal user task", "command_id": "main"},
            )
            assert response.status_code == 202
            assert response.json()["request_id"] == "main"
            await asyncio.wait_for(llm.started.wait(), 3)
            duplicate = await client.post(
                "/v2/requests",
                json={"text": "/reply literal user task", "command_id": "main"},
            )
            assert duplicate.json()["request_id"] == "main"
            assert (
                await client.post(
                    "/v2/requests", json={"text": "different", "command_id": "main"}
                )
            ).status_code == 409
            queued = await client.post(
                "/v2/requests", json={"text": "later", "command_id": "queued"}
            )
            assert queued.json()["request_id"] == "queued"
            appended = await client.post(
                "/v2/requests/queued/input",
                json={"text": "More context", "input_id": "extra"},
            )
            assert appended.status_code == 200 and appended.json()["accepted"]
            repeat = await client.post(
                "/v2/requests/queued/input",
                json={"text": "More context", "input_id": "extra"},
            )
            assert not repeat.json()["accepted"]
            full = await client.post("/v2/requests", json={"text": "overflow"})
            assert (
                full.status_code == 409
                and full.json()["error"]["code"] == "agent.queue_full"
            )
            runtime = (await client.get("/v2/status")).json()
            assert runtime["protocol_version"] == 2
            assert runtime["runtime"]["active_request_id"] == "main"
            assert runtime["runtime"]["queued_request_ids"] == ["queued"]
            assert runtime["runtime"] == agent.runtime_status()
            waiting_projection = (
                await client.get("/v2/requests/queued/interactions")
            ).json()
            assert waiting_projection["items"] == []
            assert waiting_projection["queued_request"]["delivery"] == "queued"
            assert (
                waiting_projection["pending_items"][0]["payload"]["text"]
                == "More context"
            )
            overview = (await client.get("/v2/requests/main/context")).json()
            assert overview["segments"] and overview["generation_id"]
            assert overview["captured_at"]
            assert (
                await client.get("/v2/requests/main/context/segments/inputs")
            ).status_code == 200
            assert (await client.get("/v2/expand/servers")).status_code == 200
            assert (await client.get("/v2/subagent")).status_code == 200
            assert (await client.get("/v2/home/catalog")).status_code == 200
            assert (await client.get("/v2/memory/catalog")).status_code == 200
            assert (await client.get("/v2/memory/active")).status_code == 200
            assert (await client.post("/v2/requests/queued/cancel")).json()["accepted"]
            assert (await client.get("/v2/requests/queued")).json()["result"][
                "request_failure"
            ] == "cancelled"
            llm.release.set()
            async with asyncio.timeout(4):
                while True:
                    snapshot = agent.request_snapshot("main")
                    assert snapshot is not None and snapshot.result is None
                    if snapshot.question is not None:
                        break
                    await asyncio.sleep(0.01)
            restored = (await client.get("/v2/requests/main")).json()
            assert snapshot is not None and restored == snapshot.to_json()
            assert restored["wait_reason"] == "budget"
            interactions = (await client.get("/v2/requests/main/interactions")).json()
            assert any(
                item["role"] == "agent.question" and item["options"][0]["id"] == "a"
                for item in interactions["items"]
            )
            assert (
                await client.post(
                    "/v2/requests/main/reply",
                    json={
                        "question_id": "stale",
                        "answer": {"kind": "text", "text": "A"},
                    },
                )
            ).status_code == 409
            assert (
                await client.post(
                    "/v2/requests/main/reply",
                    json={
                        "question_id": restored["question"]["question_id"],
                        "answer": {
                            "kind": "choice",
                            "option_id": "a",
                            "comment": "Proceed",
                        },
                    },
                )
            ).json()["accepted"]
            async with asyncio.timeout(4):
                while True:
                    budget = agent.request_snapshot("main")
                    assert budget is not None and budget.result is None
                    if budget.budget_request is not None:
                        break
                    await asyncio.sleep(0.01)
            assert budget is not None and budget.budget_request is not None
            grant = {
                "budget_request_id": budget.budget_request.request_id,
                "count": 1,
            }
            assert (
                await client.post(
                    "/v2/requests/main/grant", json={**grant, "count": True}
                )
            ).status_code == 422
            assert (await client.post("/v2/requests/main/grant", json=grant)).json()[
                "accepted"
            ]
            handle = agent.commands.request("main")
            assert handle is not None
            result = await asyncio.wait_for(handle.wait(), 5)
            current = (await client.get("/v2/requests/main")).json()
            assert current["state"] == "finished"
            assert current["result"] == result.to_json()
            assert current["result"]["output"]["text"] == "done"
            assert "context_completion" not in current["result"]
            saved = (await client.get("/v2/requests/main/interactions")).json()
            assert (
                saved["day"] == current["result"]["active_day"]
                and saved["generation_id"]
            )
            assert any(
                item["role"] == "user.reply"
                and item["answer"]["option_id"] == "a"
                and "Execute" in item["text"]
                for item in saved["items"]
            )
            assert (await client.get("/v2/requests/main/context")).status_code == 409
            assert (await client.get("/v2/session/turns")).status_code == 200
            assert (await client.get("/v2/session/map")).status_code == 200
            assert (await client.get("/v2/days")).status_code == 200
            unresolved = await client.get(
                "/v2/resources/resolve",
                params={"ref": "memory:latest", "day": "2000-01-01"},
            )
            assert unresolved.status_code == 422
            memory_fragment = await client.get(
                "/v2/resources/resolve",
                params={
                    "ref": "memory:current#notes",
                    "day": saved["day"],
                },
            )
            assert memory_fragment.status_code == 200
            assert memory_fragment.json()["locator"] == {
                "ref": "memory:current#notes",
                "day": saved["day"],
            }
            resolved = (
                await client.get(
                    "/v2/resources/resolve",
                    params={"ref": "workspace:note.md", "turn_id": handle.turn_id},
                )
            ).json()
            assert resolved["locator"]["day"] == saved["day"]
            assert (
                await client.post("/v2/requests/main/input", json={"text": "too late"})
            ).status_code == 409
            assert (await client.get("/v2/requests/missing")).status_code == 404
            assert (await client.get("/v1/status")).status_code == 404
            assert all(
                path.startswith("/v2/")
                for path in (await client.get("/openapi.json")).json()["paths"]
            )
            assert (await client.post("/v2/reset")).status_code == 404
    finally:
        llm.release.set()
        await agent.shutdown()


@pytest.mark.parametrize("branch", ("syntax", "owner"))
async def test_trace_locator_only_translates_context_contract_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, branch: str
) -> None:
    llm = _LLM()
    endpoints: list[EndpointEngine] = []
    agent = await _create(tmp_path, llm, endpoints=endpoints)
    await agent.start()
    try:
        handle = await agent.submit_turn(
            UserTurnRequest("Read Trace", request_id="2026-10-06/1000")
        )
        await asyncio.wait_for(llm.started.wait(), 5)
        service = agent.runtime.service_access
        valid_ref = f"turn:trace/{handle.turn_id}"
        invalid_ref = (
            "turn:trace/" if branch == "syntax" else valid_ref + "#entry/missing"
        )
        resolved = await service.resolve_resource(valid_ref, turn_id=handle.turn_id)
        locator = resolved["locator"]
        assert isinstance(locator, dict)
        assert locator["ref"] == valid_ref
        with pytest.raises(ReferenceError) as rejected:
            await service.resolve_resource(invalid_ref, turn_id=handle.turn_id)
        assert isinstance(rejected.value.__cause__, ContextContractError)

        app = create_endpoint_app(endpoints[0], endpoints[0].settings)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"Authorization": f"Bearer {'x' * 32}"},
        ) as client:
            response = await client.get(
                "/v2/resources/resolve",
                params={"ref": invalid_ref, "turn_id": handle.turn_id},
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "resource.invalid_reference"

            unexpected = (
                RuntimeError("private parser details")
                if branch == "syntax"
                else ContextInvariantError("private owner details")
            )

            def broken_parser(ref: str) -> str:
                raise unexpected

            def broken_owner(self: ContextEngine, ref: str) -> str:
                raise unexpected

            with monkeypatch.context() as patch:
                if branch == "syntax":
                    patch.setattr(
                        "tinysoul.agent.services.parse_trace_reference", broken_parser
                    )
                else:
                    patch.setattr(ContextEngine, "resolve_reference", broken_owner)
                with pytest.raises(type(unexpected)) as propagated:
                    await service.resolve_resource(valid_ref, turn_id=handle.turn_id)
                assert propagated.value is unexpected
                response = await client.get(
                    "/v2/resources/resolve",
                    params={"ref": valid_ref, "turn_id": handle.turn_id},
                )
                assert response.status_code == 500
                assert response.json()["error"]["code"] == "endpoint.internal"
                assert "private" not in response.text
    finally:
        llm.release.set()
        await agent.shutdown()


async def test_v2_job_stop_uses_turn_owner_and_sdk_projection(tmp_path: Path) -> None:
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_execution",
                "select_action_domains",
                {"domains": ["execution"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "start",
                "execution.start",
                {
                    "interpreter": "python",
                    "source_ref": "workspace:long.py",
                    "interactive": True,
                },
                ToolKind.ACTION,
            ),
            ToolCallRecord(
                "select_ask",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "ask", "core.ask", {"question": "Continue?"}, ToolKind.ACTION
            ),
        )
    ):
        llm.results.appendleft(
            TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None,
                tool_calls=(call,),
            )
        )
    endpoints: list[EndpointEngine] = []
    agent = await _create(tmp_path, llm, endpoints=endpoints)
    await agent.start()
    try:
        await agent.patch_config(
            (
                ConfigMutation(
                    source_id="project:configs/execution.toml",
                    path="execution.enabled",
                    op="set",
                    value=True,
                ),
                ConfigMutation(
                    source_id="project:configs/execution.toml",
                    path="execution.interpreters.python.executable",
                    op="set",
                    value=sys.executable,
                ),
            )
        )
        await agent.reload_config()
        await agent.services.get(WorkspaceService).write_text(
            "workspace:long.py", "import sys; sys.stdin.read()"
        )
        llm.release.set()
        active = await agent.submit_turn(UserTurnRequest("Run", request_id="owner"))
        async with asyncio.timeout(5):
            while active.question is None:
                assert not active.done, active.result
                await asyncio.sleep(0.01)
        snapshots = agent.turn_jobs(active.request_id)
        assert snapshots and not snapshots[0].state.terminal
        endpoint = endpoints[0]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_endpoint_app(endpoint, endpoint.settings)
            ),
            base_url="http://test",
            headers={"Authorization": f"Bearer {'x' * 32}"},
        ) as client:
            jobs = (await client.get("/v2/requests/owner/jobs")).json()["jobs"]
            assert jobs == [item.to_json() for item in snapshots]
            job_id = snapshots[0].job_id
            detail = await client.get(f"/v2/requests/owner/jobs/{job_id}")
            assert detail.status_code == 200 and detail.json()["job_id"] == job_id
            output = await client.get(f"/v2/requests/owner/jobs/{job_id}/output")
            assert output.status_code == 200 and "items" in output.json()
            again = await client.get(f"/v2/requests/owner/jobs/{job_id}/output")
            assert again.json() == output.json()
            invalid_output = await client.get(
                f"/v2/requests/owner/jobs/{job_id}/output",
                params={"continuation": "invalid"},
            )
            assert invalid_output.status_code == 409
            assert (
                await client.post(f"/v2/requests/wrong/jobs/{job_id}/stop")
            ).status_code == 404
            stopped = await client.post(f"/v2/requests/owner/jobs/{job_id}/stop")
            assert stopped.status_code == 200 and stopped.json()["state"] in {
                "cancelled",
                "succeeded",
            }
            current = agent.turn_jobs("owner")
            assert current and stopped.json() == current[0].to_json()
            assert not active.cancel_requested
            await client.post("/v2/requests/owner/cancel")
            await asyncio.wait_for(active.wait(), 5)
            assert (await client.get("/v2/requests/owner/jobs")).json()["jobs"] == []
            assert (
                await client.post(f"/v2/requests/owner/jobs/{job_id}/stop")
            ).status_code == 404
    finally:
        await agent.shutdown()
