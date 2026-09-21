"""ACP SDK server exercising prompt, permissions and session reuse without a model."""

import asyncio
import json
from typing import Any

from acp import Agent, Client, run_agent
from acp.schema import (
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    AgentMessageChunk,
    TextContentBlock,
    ToolCallUpdate,
    PermissionOption,
)
from acp.schema import (
    ClientCapabilities,
    Implementation,
    HttpMcpServer,
    SseMcpServer,
    AcpMcpServer,
    McpServerStdio,
)


class LocalAgent(Agent):
    def __init__(self) -> None:
        self.sessions: dict[str, int] = {}
        self.number = 0
        self.client: Client
        self.cancelled: dict[str, asyncio.Event] = {}
        self.background: set[str] = set()

    def on_connect(self, conn: Client) -> None:
        self.client = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse.model_validate(
            {
                "protocolVersion": 1,
                "agentCapabilities": {"sessionCapabilities": {"close": {}}},
                "agentInfo": {"name": "local-acp", "version": "1"},
                "authMethods": [],
            }
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | AcpMcpServer | McpServerStdio]
        | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        self.number += 1
        identity = f"session_{self.number}"
        self.sessions[identity] = 0
        self.cancelled[identity] = asyncio.Event()
        return NewSessionResponse(session_id=identity)

    async def prompt(
        self, session_id: str, prompt: Any, **kwargs: Any
    ) -> PromptResponse:
        self.sessions[session_id] += 1
        instruction = " ".join(item.text for item in prompt)
        background = "background" in instruction
        if "permission" in instruction:
            answer = await self.client.request_permission(
                session_id=session_id,
                tool_call=ToolCallUpdate(
                    tool_call_id="command", title="Allow this local test?"
                ),
                options=[
                    PermissionOption(
                        option_id="yes_once", name="Allow once", kind="allow_once"
                    ),
                    PermissionOption(
                        option_id="no_once", name="Reject once", kind="reject_once"
                    ),
                ],
            )
            instruction = str(answer.outcome.model_dump())
        if "wait_forever" in instruction:
            await self.cancelled[session_id].wait()
            return PromptResponse(stop_reason="cancelled")
        if "ignore_cancel" in instruction:
            await asyncio.Event().wait()
        if background:
            self.background.add(session_id)
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "async_task_spawned",
                                "asyncTaskId": "terminal_1",
                                "taskType": "shell",
                                "name": "fixture",
                            },
                        },
                    }
                ),
                flush=True,
            )
        await self.client.session_update(
            session_id,
            AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(
                    type="text",
                    text=f"context {session_id}; invocation {self.sessions[session_id]}; active {len(self.background)}; {instruction}",
                ),
            ),
        )
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self.cancelled[session_id].set()

    async def close_session(self, session_id: str, **kwargs: Any) -> None:
        del self.sessions[session_id]
        del self.cancelled[session_id]

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "session/async_task/stop":
            self.background.discard(params["sessionId"])
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": params["sessionId"],
                            "update": {
                                "sessionUpdate": "async_task_state_update",
                                "asyncTaskId": params["asyncTaskId"],
                                "state": "stopped",
                            },
                        },
                    }
                ),
                flush=True,
            )
        return {"stopped": True}


if __name__ == "__main__":
    asyncio.run(run_agent(LocalAgent(), use_unstable_protocol=True))
