from pathlib import Path
from time import monotonic
from typing import cast

import pytest
from mcp import Client
from mcp.types import ListToolsResult, Tool, ToolListChangedNotification

from tinysoul.plugins.capabilities.expand.config import (
    ExpandSettings,
    MCPServerSettings,
)
from tinysoul.plugins.capabilities.expand.mcp.client import MCPConnection
from tinysoul.plugins.capabilities.expand.failures import ExpandRequestError


async def test_directory_pagination_ttl_notification_and_failed_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SDK:
        calls = 0
        changed = False
        fail_second = False

        async def list_tools(self, cursor: str | None = None) -> ListToolsResult:
            self.calls += 1
            if cursor and self.fail_second:
                raise OSError("remote details")
            name = "new" if self.changed else "first"
            return ListToolsResult(
                tools=[
                    Tool(
                        name=name if cursor is None else "second",
                        input_schema={"type": "object"},
                    )
                ],
                ttl_ms=10000 if cursor is None else 2000,
                next_cursor="page2" if cursor is None else None,
            )

    sdk = SDK()
    connection = MCPConnection(
        MCPServerSettings("local"), ExpandSettings(), root=tmp_path, environment={}
    )

    async def connect() -> Client:
        return cast(Client, sdk)

    monkeypatch.setattr(connection, "_connect", connect)
    first = await connection.directory()
    assert len(first.tools) == 2 and sdk.calls == 2
    assert first.expires_at <= monotonic() + 2.1
    assert await connection.directory() is first and sdk.calls == 2
    await connection._notification(ToolListChangedNotification())
    assert connection.directory_identity is None
    sdk.changed = True
    changed = await connection.directory()
    assert changed.tools[0]["name"] == "new" and sdk.calls == 4
    connection.invalidate()
    sdk.fail_second = True
    with pytest.raises(ExpandRequestError):
        await connection.directory()
    assert connection.directory_identity is None
    sdk.fail_second = False
    assert len((await connection.directory()).tools) == 2
