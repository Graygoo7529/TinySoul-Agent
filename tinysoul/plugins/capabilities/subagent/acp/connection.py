"""Codex ACP session adapter; protocol identifiers never enter generic Context."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from acp import Agent as AcpAgent, Client, connect_to_agent
from acp.exceptions import RequestError
from acp.schema import (
    ClientCapabilities,
    CreateElicitationResponse,
    CreateTerminalResponse,
    Implementation,
    KillTerminalResponse,
    ReadTextFileResponse,
    ReleaseTerminalResponse,
    RequestPermissionResponse,
    TerminalOutputResponse,
    TextContentBlock,
    WaitForTerminalExitResponse,
    WriteTextFileResponse,
)

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.process import ManagedProcessRequest, StdioProcess
from ..config import AgentTarget, SubagentSettings
from ..failures import SubagentFailure, SubagentRequestError


class PromptReceiver(Protocol):
    async def permission(
        self, question: str, options: tuple[tuple[str, str], ...]
    ) -> str | None: ...
    async def text(self, text: str) -> None: ...


class _Client(Client):
    def __init__(self, owner: ACPConnection) -> None:
        self._owner = owner

    async def request_permission(
        self, session_id: str, tool_call: Any, options: Any, **kwargs: Any
    ) -> RequestPermissionResponse:
        receiver = self._owner.receiver
        selected = None
        if receiver is not None:
            selected = await receiver.permission(
                str(tool_call.title or "External Agent requests permission")[:1000],
                tuple((str(option.option_id), str(option.name)) for option in options),
            )
        return RequestPermissionResponse.model_validate(
            {
                "outcome": {"outcome": "selected", "optionId": selected}
                if selected is not None
                else {"outcome": "cancelled"}
            }
        )

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if (
            self._owner.receiver is not None
            and update.session_update == "agent_message_chunk"
        ):
            content = update.content
            if isinstance(content, TextContentBlock):
                await self._owner.receiver.text(content.text)

    async def write_text_file(
        self, session_id: str, path: str, content: str, **kwargs: Any
    ) -> WriteTextFileResponse | None:
        raise self._unsupported("file write")

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> ReadTextFileResponse:
        raise self._unsupported("file read")

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: list[Any] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> CreateTerminalResponse:
        raise self._unsupported("terminal creation")

    async def terminal_output(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> TerminalOutputResponse:
        raise self._unsupported("terminal output")

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> ReleaseTerminalResponse | None:
        raise self._unsupported("terminal release")

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> WaitForTerminalExitResponse:
        raise self._unsupported("terminal wait")

    async def kill_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> KillTerminalResponse | None:
        raise self._unsupported("terminal kill")

    async def create_elicitation(
        self, message: str, mode: Any, **kwargs: Any
    ) -> CreateElicitationResponse:
        raise self._unsupported("elicitation")

    async def complete_elicitation(self, elicitation_id: str, **kwargs: Any) -> None:
        # Notifications have no response; this client never opens elicitation.
        return None

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise self._unsupported("extension method")

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        return None

    def on_connect(self, conn: AcpAgent) -> None:
        return None

    @staticmethod
    def _unsupported(capability: str) -> RequestError:
        return RequestError.method_not_found(capability)


class _Transport:
    """Decode Codex extension updates before the ACP v1 SDK's closed update union."""

    def __init__(
        self, process: StdioProcess, extension: Callable[[JsonObject], None]
    ) -> None:
        self._process, self._extension = process, extension

    async def send(self, message: dict[str, Any]) -> None:
        self._process.stdin.write((json.dumps(message) + "\n").encode())
        await self._process.stdin.drain()

    async def receive(self) -> dict[str, Any] | None:
        while line := await self._process.stdout.readline():
            message = to_json_object(json.loads(line))
            params = message.get("params")
            if message.get("method") == "session/update" and isinstance(params, dict):
                update = params.get("update")
                if isinstance(update, dict) and update.get("sessionUpdate") in {
                    "async_task_spawned",
                    "async_task_state_update",
                }:
                    self._extension(update)
                    continue
            return message
        return None

    async def close(self) -> None:
        self._process.stdin.close()


class ACPConnection:
    def __init__(self, process: StdioProcess, settings: SubagentSettings) -> None:
        self._process, self._settings = process, settings
        self.receiver: PromptReceiver | None = None
        self._background: set[str] = set()
        self._background_changed = asyncio.Event()
        self._rpc = connect_to_agent(
            _Client(self), _Transport(process, self._extension)
        )
        self._session_id: str | None = None
        self._can_close_session = False
        self._closed = False

    @classmethod
    async def connect(
        cls,
        target: AgentTarget,
        settings: SubagentSettings,
        cwd: Path,
        environment: Mapping[str, str],
    ) -> ACPConnection:
        process = await StdioProcess.start(
            ManagedProcessRequest(
                (target.command, *target.args),
                cwd=str(cwd),
                env={
                    **environment,
                    "NO_BROWSER": "1",
                    "INITIAL_AGENT_MODE": "agent-full-access"
                    if target.auto_approve
                    else "agent",
                },
            )
        )
        connection = cls(process, settings)
        try:
            async with asyncio.timeout(settings.connect_timeout_seconds):
                initialized = await connection._rpc.initialize(
                    1,
                    client_capabilities=ClientCapabilities.model_validate(
                        {
                            "_meta": {
                                "jetbrains": {
                                    "air": {
                                        "version": 1,
                                        "capabilities": ["asyncTasks"],
                                    }
                                }
                            }
                        }
                    ),
                    client_info=Implementation(name="TinySoul", version="0.1"),
                )
                capabilities = initialized.agent_capabilities
                sessions = (
                    capabilities.session_capabilities
                    if capabilities is not None
                    else None
                )
                connection._can_close_session = (
                    sessions is not None and sessions.close is not None
                )
                await connection.new_session(cwd)
            return connection
        except BaseException:
            await connection.close()
            raise

    @property
    def closed(self) -> bool:
        return self._closed

    async def new_session(self, cwd: Path) -> None:
        async with asyncio.timeout(self._settings.connect_timeout_seconds):
            session = await self._rpc.new_session(str(cwd), mcp_servers=[])
            self._session_id = session.session_id

    async def prompt(self, brief: str, receiver: PromptReceiver) -> str:
        if self._session_id is None or self.receiver is not None or self._closed:
            raise SubagentRequestError(
                SubagentFailure.BUSY, "ACP session is not ready for a new delegation."
            )
        self.receiver = receiver
        try:
            response = await self._rpc.prompt(
                session_id=self._session_id,
                prompt=[TextContentBlock(type="text", text=brief)],
            )
            return response.stop_reason
        finally:
            self.receiver = None

    def _extension(self, update: JsonObject) -> None:
        identity = update.get("asyncTaskId")
        if not isinstance(identity, str):
            return
        if update.get("sessionUpdate") == "async_task_spawned":
            self._background.add(identity)
        elif update.get("state") in {"completed", "failed", "stopped"}:
            self._background.discard(identity)
        self._background_changed.set()

    async def cancel(self) -> None:
        if self._session_id is not None and not self._closed:
            await self._rpc.cancel(self._session_id)

    async def close_execution(self) -> None:
        if self._closed:
            return
        try:
            async with asyncio.timeout(self._settings.stop_timeout_seconds):
                for identity in tuple(self._background):
                    await self._rpc.ext_method(
                        "session/async_task/stop",
                        {"sessionId": self._session_id, "asyncTaskId": identity},
                    )
                while self._background:
                    self._background_changed.clear()
                    await self._background_changed.wait()
        except Exception:
            # An unresponsive external execution loses its reusable connection.
            # The process tree is still stopped before the Job can close.
            await self.close()

    async def release_session(self) -> None:
        if self._session_id is None:
            return
        if not self._can_close_session:
            await self.close()
            return
        try:
            async with asyncio.timeout(self._settings.stop_timeout_seconds):
                await self.close_execution()
                if not self._closed:
                    await self._rpc.close_session(self._session_id)
                    self._session_id = None
        except Exception:
            await self.close()

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        if self._closed:
            return ()
        diagnostics = await self._process.close()
        self._closed = True
        try:
            await self._rpc.close()
        except Exception as exc:
            diagnostics = (
                *diagnostics,
                CleanupDiagnostic("subagent.connection", type(exc).__name__),
            )
        self._session_id = None
        self._background.clear()
        return diagnostics
