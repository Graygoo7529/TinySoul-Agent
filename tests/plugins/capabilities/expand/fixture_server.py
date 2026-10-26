"""Local MCP protocol fixture, usable over stdio and HTTP without model calls."""

import sys
import asyncio
import os
import socket
from pathlib import Path

from mcp.server.mcpserver import MCPServer

server = MCPServer("local-test")


@server.tool()
def add(a: int, b: int) -> dict[str, int]:
    """Add two integers."""
    return {"value": a + b}


@server.tool()
def long_text() -> str:
    """Produce a resource-sized result."""
    return "useful output\n" * 2000


if os.environ.get("TINYSOUL_MCP_FIXTURE_EXTENDED") == "1":
    from mcp.types import CallToolResult, ImageContent, TextContent

    @server.tool()
    def image() -> CallToolResult:
        return CallToolResult(
            content=[
                ImageContent(type="image", mime_type="image/png", data="cG5nLWJ5dGVz")
            ]
        )

    @server.tool()
    def remote_error() -> CallToolResult:
        return CallToolResult(
            is_error=True, content=[TextContent(type="text", text="Request rejected")]
        )

    @server.tool()
    def lost_reply() -> str:
        """Change state and exit before returning a response."""
        with Path("call-count.txt").open("a", encoding="utf-8") as output:
            output.write("1\n")
        os._exit(0)


def serve_http() -> None:
    import uvicorn

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))

        class ReadyServer(uvicorn.Server):
            async def startup(self, sockets: list[socket.socket] | None = None) -> None:
                await super().startup(sockets)
                print(listener.getsockname()[1], flush=True)

        host = ReadyServer(
            uvicorn.Config(server.streamable_http_app(), log_level="warning")
        )
        asyncio.run(host.serve(sockets=[listener]))


if __name__ == "__main__":
    if sys.argv[1:] == ["--http"]:
        serve_http()
    else:
        server.run()
