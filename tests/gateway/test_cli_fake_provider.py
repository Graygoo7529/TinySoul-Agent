from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import signal
from pathlib import Path
from threading import Thread
from typing import cast

import pytest
import httpx

from tinysoul.gateway import cli
from tinysoul.agent import AgentClosedError, UserTurnRequest
from tinysoul.agent.composition.assembly import AgentAssembly
from tinysoul.agent.composition.builder import AgentBuilder
from tinysoul.gateway.endpoint import EndpointHost, EndpointReady, EndpointSettings
from tinysoul.infra import ConfigEnvironment
from tinysoul.runtime import ObservationEvent, ObservationLevel, RuntimeException
from tests.support.project import copy_initialized_project


async def test_cli_host_survives_http_restart_failure_and_uses_current_commands(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent"
    copy_initialized_project(root)
    ready = asyncio.get_running_loop().create_future()
    handshakes: list[EndpointReady] = []

    def on_ready(value: EndpointReady) -> None:
        handshakes.append(value)
        ready.set_result(value)

    host = EndpointHost(settings=EndpointSettings(token="x" * 32), ready=on_ready)
    assemblies: list[AgentAssembly] = []
    rebuilding = asyncio.Event()
    release = asyncio.Event()
    fail_build = False

    async def factory() -> AgentAssembly:
        if assemblies:
            rebuilding.set()
            await release.wait()
        if fail_build:
            raise RuntimeException("runtime.startup_failed", "private startup detail")
        assembly = await (
            AgentBuilder(root).with_config_environment(
                ConfigEnvironment.from_project_root(root, env={}, overrides={
                    "agent.interactive": False,
                    "reflection.schedule.enabled": False,
                    "workspace.watch.enabled": False,
                })
            ).build()
        )
        host.bind(assembly)
        assemblies.append(assembly)
        return assembly

    application = asyncio.create_task(cli._run_application(factory, None, host))
    try:
        connection = await asyncio.wait_for(ready, 5)
        async with httpx.AsyncClient(
            base_url=f"http://{connection.host}:{connection.port}",
            headers={"Authorization": f"Bearer {connection.token}"},
            trust_env=False,
            timeout=10,
        ) as client:
            before = (await client.get("/v2/status")).json()
            engine = host.engine
            old_commands = assemblies[0].commands
            restarting = asyncio.create_task(client.post("/v2/restart"))
            try:
                await asyncio.wait_for(rebuilding.wait(), 5)
                assert (await client.get("/v2/status")).json()["ready"] is False
                refused = await client.post("/v2/turns", json={"kind": "user", "text": "during restart"})
                assert refused.status_code == 409
                assert refused.json()["error"]["code"] == "service.unavailable"
            finally:
                release.set()
            response = await restarting
            assert response.status_code == 202
            after = (await client.get("/v2/status")).json()
            assert after["runtime"]["generation_id"] != before["runtime"]["generation_id"]
            assert after["instance_id"] == before["instance_id"]
            assert host.engine is engine and len(handshakes) == 1
            assert not application.done()
            with pytest.raises(AgentClosedError):
                await old_commands.submit_turn(UserTurnRequest("old facade"))

            cursor = before["latest_event_sequence"]
            for assembly in assemblies:
                assembly.observations.emit(ObservationEvent(
                    name="test.bound", source="test", level=ObservationLevel.NORMAL,
                ))
            replay = (await client.get("/v2/events", params={"after": cursor})).json()
            assert replay["gap"] is False
            assert sum(event["name"] == "test.bound" for event in replay["events"]) == 1

            fail_build = True
            failed = await client.post("/v2/restart")
            assert failed.status_code == 503
            assert failed.json()["error"]["code"] == "agent.restart_failed"
            assert "private startup detail" not in failed.text
            assert (await client.get("/v2/status")).json()["ready"] is False
            assert not application.done()
            fail_build = False
            assert (await client.post("/v2/restart")).status_code == 202
            assert (await client.get("/v2/status")).json()["ready"] is True
            assert len(handshakes) == 1

            # Exercise the installed CLI handler after two generation replacements.
            handler = signal.getsignal(signal.SIGINT)
            assert handler is not None and not isinstance(handler, int)
            handler(signal.SIGINT, None)
            assert await asyncio.wait_for(application, 5) == 0
    finally:
        release.set()
        if not application.done():
            application.cancel()
        await asyncio.gather(application, return_exceptions=True)


class _FakeProviderServer(ThreadingHTTPServer):
    requests: list[dict[str, object]]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeProviderHandler)
        self.requests = []


class _FakeProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server = cast(_FakeProviderServer, self.server)
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        assert isinstance(payload, dict)
        server.requests.append(payload)
        response = _provider_response(len(server.requests) - 1)
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_initialized_project_runs_cli_through_fake_openai_provider(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1")
    root = tmp_path / "agent"
    copy_initialized_project(root)

    with _fake_provider() as server:
        _configure_fake_provider(root, port=server.server_port)

        result = cli.main(["start", "--root", str(root), "--once", "say hello"])

    captured = capsys.readouterr()
    assert result == 0, captured.err
    assert "hello from fake provider" in captured.out
    assert len(server.requests) == 3
    assert all(request.get("model") == "fake-model" for request in server.requests)


@contextmanager
def _fake_provider() -> Iterator[_FakeProviderServer]:
    server = _FakeProviderServer()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _configure_fake_provider(root: Path, *, port: int) -> None:
    (root / ".env").write_text("FAKE_API_KEY=test-key\n", encoding="utf-8")
    (root / "configs" / "llm" / "providers.toml").write_text(
        "[llm.providers.fake]\n"
        "enabled = true\n"
        'adapters = ["openai_compatible_chat"]\n'
        f'base_url = "http://127.0.0.1:{port}/v1"\n'
        'api_key_envs = ["FAKE_API_KEY"]\n',
        encoding="utf-8",
    )
    model_root = root / "configs" / "llm" / "models"
    for path in model_root.glob("*.toml"):
        path.unlink()
    (model_root / "fake.toml").write_text(
        "[llm.models.fake_model]\n"
        'adapter = "openai_compatible_chat"\n'
        'providers = [{ provider = "fake", provider_model = "fake-model" }]\n'
        "context_window_tokens = 262144\n"
        "capabilities = [\n"
        '  "text_input",\n'
        '  "json_object_output",\n'
        '  "tool_calling",\n'
        "]\n",
        encoding="utf-8",
    )
    (root / "configs" / "llm" / "tasks.toml").write_text(
        "\n".join(
            (
                _task_config("frame_stage1"),
                _task_config("frame_stage2"),
                _task_config("llm_action"),
            )
        ),
        encoding="utf-8",
    )


def _task_config(profile: str) -> str:
    return (
        f"[llm.tasks.{profile}]\n"
        'models = ["fake_model"]\n'
        'required_capabilities = ["text_input"]\n'
        'answer_format = "json_object"\n'
        'tool_use = "disabled"\n'
        "temperature = 0.0\n"
        "max_output_tokens = 1024\n"
        "max_retries_per_provider = 1\n"
        "retry_wait_seconds = 0.0\n"
        "provider_switch_wait_seconds = 0.0\n"
        "model_switch_wait_seconds = 0.0\n"
        "max_cycles = 1\n"
        "prefer_successful_model_seconds = 0\n"
    )


def _provider_response(index: int) -> dict[str, object]:
    if index == 0:
        message = _tool_call_message(
            "select_1",
            "select_action_domains",
            {"domains": ["core"]},
        )
        finish_reason = "tool_calls"
    elif index == 1:
        message = _tool_call_message(
            "answer_1",
            "core.answer",
            {"guide_blocks": [{"text": "Answer the user directly."}]},
        )
        finish_reason = "tool_calls"
    else:
        message = {
            "role": "assistant",
            "content": json.dumps({"text": "hello from fake provider"}),
        }
        finish_reason = "stop"
    return {
        "id": f"chatcmpl-{index}",
        "object": "chat.completion",
        "created": 0,
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }


def _tool_call_message(
    call_id: str,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
    }
