from pathlib import Path
import sys
import socket
import asyncio

import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.process import ManagedProcessRequest, StdioProcess
from tinysoul.plugins.capabilities.expand.config import (
    ExpandSettings,
    MCPServerSettings,
    MCPTransport,
)
from tinysoul.plugins.capabilities.expand.engine import ExpandEngine
from tinysoul.plugins.capabilities.expand.failures import (
    ExpandFailure,
    ExpandRequestError,
)
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings


async def test_real_sdk_stdio_discovery_validation_and_resource_output(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine = ExpandEngine(
        ExpandSettings(
            servers=(
                MCPServerSettings(
                    "local",
                    enabled=True,
                    command=sys.executable,
                    args=(str(Path(__file__).with_name("fixture_server.py")),),
                ),
            )
        ),
        root=tmp_path,
        workspace=workspace,
        environment={},
    )
    try:
        directory = await engine.discover()
        assert directory.servers[0]["status"] == "available"
        assert {item.name for item in directory.tools} == {"add", "long_text"}
        assert all(not item.problem for item in directory.tools)
        result = await engine.call(
            "local", "add", {"a": 2, "b": 3}, operations=JoinedOperations()
        )
        assert result["structured"] == {"value": 5}
        with pytest.raises(ExpandRequestError) as raised:
            await engine.call(
                "local", "add", {"a": "wrong", "b": 3}, operations=JoinedOperations()
            )
        assert raised.value.reason is ExpandFailure.ARGUMENTS
        output = await engine.call(
            "local", "long_text", {}, operations=JoinedOperations()
        )
        assert "workspace:mcp/" in str(output)
        assert workspace.snapshot().resources
    finally:
        await engine.close()


async def test_real_sdk_streamable_http_discovery_and_call(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server_process = await StdioProcess.start(
        ManagedProcessRequest(
            (
                sys.executable,
                str(Path(__file__).with_name("fixture_server.py")),
                "--http",
                str(port),
            )
        )
    )
    engine = ExpandEngine(
        ExpandSettings(
            servers=(
                MCPServerSettings(
                    "http",
                    enabled=True,
                    transport=MCPTransport.HTTP,
                    url=f"http://127.0.0.1:{port}/mcp",
                ),
            )
        ),
        root=tmp_path,
        workspace=WorkspaceEngineBuilder(
            WorkspaceSettings(root=tmp_path / "workspace")
        ).build(),
        environment={},
    )
    try:
        directory = None
        for _ in range(30):
            directory = await engine.discover()
            if directory.servers[0]["status"] == "available":
                break
            await asyncio.sleep(0.1)
        assert directory is not None
        assert directory.servers[0]["status"] == "available"
        result = await engine.call(
            "http", "add", {"a": 4, "b": 5}, operations=JoinedOperations()
        )
        assert result["structured"] == {"value": 9}
    finally:
        await engine.close()
        await server_process.close()


async def test_mcp_error_binary_policy_and_lost_write_reply(tmp_path: Path) -> None:
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine = ExpandEngine(
        ExpandSettings(
            timeout_seconds=3,
            servers=(
                MCPServerSettings(
                    "local",
                    enabled=True,
                    command=sys.executable,
                    args=(str(Path(__file__).with_name("fixture_server.py")),),
                    env=(("TINYSOUL_MCP_FIXTURE_EXTENDED", "1"),),
                    tools=(("add", False),),
                ),
            ),
        ),
        root=tmp_path,
        workspace=workspace,
        environment={},
    )
    try:
        assert "add" not in {item.name for item in (await engine.discover()).tools}
        with pytest.raises(ExpandRequestError):
            await engine.call(
                "local", "add", {"a": 1, "b": 2}, operations=JoinedOperations()
            )
        image = await engine.call("local", "image", {}, operations=JoinedOperations())
        assert "workspace:mcp/" in str(image) and "cG5nLWJ5dGVz" not in str(image)
        error = await engine.call(
            "local", "remote_error", {}, operations=JoinedOperations()
        )
        assert error["is_error"] is True
        with pytest.raises(ExpandRequestError) as failure:
            await engine.call("local", "lost_reply", {}, operations=JoinedOperations())
        assert failure.value.reason is ExpandFailure.RESULT_UNKNOWN
        assert (tmp_path / "call-count.txt").read_text(encoding="utf-8") == "1\n"
    finally:
        await engine.close()
