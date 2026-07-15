from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from typing import cast

import pytest

from tinysoul.app import cli


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
) -> None:
    root = tmp_path / "agent"
    assert cli.main(["init", str(root)]) == 0

    with _fake_provider() as server:
        _configure_fake_provider(root, port=server.server_port)

        result = cli.main(["--root", str(root), "--once", "say hello"])

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
    (root / "configs" / "llm.providers.toml").write_text(
        "[llm.providers.fake]\n"
        "enabled = true\n"
        'adapter = "generic"\n'
        'api_style = "openai_chat"\n'
        f'base_url = "http://127.0.0.1:{port}/v1"\n'
        'api_key_envs = ["FAKE_API_KEY"]\n',
        encoding="utf-8",
    )
    model_root = root / "configs" / "llm.models"
    for path in model_root.glob("*.toml"):
        path.unlink()
    (model_root / "fake.toml").write_text(
        "[llm.models.fake_model]\n"
        'provider = "fake"\n'
        'provider_model = "fake-model"\n'
        "capabilities = [\n"
        '  "text_input",\n'
        '  "json_object_output",\n'
        '  "tool_calling",\n'
        "]\n",
        encoding="utf-8",
    )
    (root / "configs" / "llm.tasks.toml").write_text(
        _task_config("framework") + "\n" + _task_config("llm_action"),
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
        "max_retries_per_model = 1\n"
        "retry_wait_seconds = 0.0\n"
        "switch_wait_seconds = 0.0\n"
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
