"""One SDK Client for modern and legacy MCP, with owner-controlled lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
import httpx2
from mcp import Client
from mcp.client import InputRequiredRoundsExceededError
from mcp.client.session import IncomingMessage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from mcp.types import jsonrpc_message_adapter, ServerNotification

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.config.validation import resolve_references
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.process import ManagedProcessRequest, StdioProcess
from ..config import ExpandSettings, MCPServerSettings, MCPTransport
from ..failures import ExpandFailure, ExpandRequestError


@dataclass(frozen=True)
class ToolDirectory:
    tools: tuple[JsonObject, ...]
    expires_at: float


@asynccontextmanager
async def _stdio(
    process: StdioProcess,
) -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    sender, reader = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    writer, receiver = anyio.create_memory_object_stream[SessionMessage](0)

    async def read() -> None:
        async with sender:
            while line := await process.stdout.readline():
                try:
                    value = SessionMessage(jsonrpc_message_adapter.validate_json(line))
                except ValueError as exc:
                    await sender.send(exc)
                    return
                await sender.send(value)

    async def write() -> None:
        async with receiver:
            async for value in receiver:
                process.stdin.write(
                    (
                        value.message.model_dump_json(by_alias=True, exclude_none=True)
                        + "\n"
                    ).encode()
                )
                await process.stdin.drain()

    async with anyio.create_task_group() as group:
        group.start_soon(read)
        group.start_soon(write)
        try:
            yield reader, writer
        finally:
            group.cancel_scope.cancel()
    await reader.aclose()
    await writer.aclose()


class MCPConnection:
    """A generation-owned connection. No independent job or persistent tool database."""

    def __init__(
        self,
        server: MCPServerSettings,
        settings: ExpandSettings,
        *,
        root: Path,
        environment: Mapping[str, str],
    ) -> None:
        self.server, self._settings, self._root = server, settings, root
        key = f"capabilities.expand.servers.{server.server_id}"
        self._env = resolve_references(
            server.env, server.env_refs, environment, key=f"{key}.env_refs"
        )
        self._headers = resolve_references(
            server.headers, server.header_refs, environment, key=f"{key}.header_refs"
        )
        self._client: Client | None = None
        self._process: StdioProcess | None = None
        self._lifetime: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._directory: ToolDirectory | None = None
        self._dirty = True

    def invalidate(self) -> None:
        self._dirty = True

    @property
    def directory_identity(self) -> ToolDirectory | None:
        """Private cache identity consumed by owner pagination, never by the model."""
        return None if self._dirty else self._directory

    async def _notification(self, message: IncomingMessage) -> None:
        if isinstance(message, Exception) or (
            isinstance(message, ServerNotification)
            and message.method == "notifications/tools/list_changed"
        ):
            self.invalidate()

    async def _serve(self, ready: asyncio.Future[Client]) -> None:
        try:
            async with AsyncExitStack() as stack:
                if self.server.transport is MCPTransport.STDIO:
                    cwd = Path(self.server.cwd) if self.server.cwd else self._root
                    if not cwd.is_absolute():
                        cwd = self._root / cwd
                    self._process = await StdioProcess.start(
                        ManagedProcessRequest(
                            (self.server.command, *self.server.args),
                            cwd=str(cwd),
                            env=self._env,
                        ),
                        max_message_bytes=self._settings.max_result_bytes,
                    )
                    transport = _stdio(self._process)
                else:
                    http = await stack.enter_async_context(
                        httpx2.AsyncClient(
                            headers=self._headers,
                            timeout=self._settings.timeout_seconds,
                        )
                    )
                    transport = streamable_http_client(
                        self.server.url, http_client=http
                    )
                client = await stack.enter_async_context(
                    Client(
                        transport,
                        cache=None,
                        read_timeout_seconds=self._settings.timeout_seconds,
                        input_required_max_rounds=0,
                        message_handler=self._notification,
                    )
                )
                self._client = client
                listener = asyncio.create_task(self._listen(client))
                ready.set_result(client)
                try:
                    await self._stop.wait()
                finally:
                    listener.cancel()
                    try:
                        await listener
                    except asyncio.CancelledError:
                        pass
        except Exception:
            if not ready.done():
                ready.set_exception(
                    ExpandRequestError(
                        ExpandFailure.UNAVAILABLE, "MCP server could not connect."
                    )
                )
            else:
                self._dirty = True
        finally:
            self._client = None
            if self._process is not None:
                await self._process.close()
                self._process = None

    async def _listen(self, client: Client) -> None:
        try:
            async with client.listen(tools_list_changed=True) as subscription:
                async for _ in subscription:
                    self.invalidate()
        except Exception:
            # Legacy or unavailable subscriptions remain correct through TTL /
            # access refresh; no background reconnect or alternate client.
            self.invalidate()

    async def _connect(self) -> Client:
        if self._client is not None:
            return self._client
        if self._lifetime is not None:
            await self.close()
        self._stop = asyncio.Event()
        ready = asyncio.get_running_loop().create_future()
        self._lifetime = asyncio.create_task(self._serve(ready))
        try:
            return await asyncio.wait_for(
                asyncio.shield(ready), self._settings.timeout_seconds
            )
        except BaseException as exc:
            await self.close()
            if isinstance(exc, TimeoutError):
                raise ExpandRequestError(
                    ExpandFailure.UNAVAILABLE, "MCP connection timed out."
                ) from exc
            raise

    async def directory(self) -> ToolDirectory:
        async with self._lock:
            if (
                self._directory is not None
                and not self._dirty
                and monotonic() < self._directory.expires_at
            ):
                return self._directory
            client = await self._connect()
            tools: list[JsonObject] = []
            cursor: str | None = None
            seen: set[str] = set()
            total_bytes = 0
            expiry = float("inf")
            self._dirty = False
            try:
                async with asyncio.timeout(self._settings.timeout_seconds):
                    while True:
                        page = await client.list_tools(cursor=cursor)
                        expiry = min(expiry, monotonic() + page.ttl_ms / 1000)
                        for tool in page.tools:
                            total_bytes += len(tool.model_dump_json().encode())
                            tools.append(
                                to_json_object(
                                    tool.model_dump(
                                        by_alias=True, mode="json", exclude_none=True
                                    )
                                )
                            )
                        if (
                            len(tools) > self._settings.max_tools
                            or total_bytes > self._settings.max_catalog_bytes
                        ):
                            raise ExpandRequestError(
                                ExpandFailure.CAPACITY,
                                "Server tool directory exceeds its configured bound.",
                            )
                        cursor = page.next_cursor
                        if cursor is None:
                            break
                        if cursor in seen or len(seen) >= self._settings.max_tools:
                            raise ExpandRequestError(
                                ExpandFailure.REMOTE,
                                "Server tool pagination did not converge.",
                            )
                        seen.add(cursor)
            except ExpandRequestError:
                self._dirty = True
                raise
            except Exception as exc:
                self._dirty = True
                raise ExpandRequestError(
                    ExpandFailure.UNAVAILABLE, "MCP tool directory is unavailable."
                ) from exc
            self._directory = ToolDirectory(tuple(tools), expiry)
            return self._directory

    async def call(self, name: str, arguments: JsonObject) -> JsonObject:
        async with self._lock:
            client = await self._connect()
            try:
                async with asyncio.timeout(self._settings.timeout_seconds):
                    result = await client.call_tool(name, arguments)
                return to_json_object(
                    result.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
            except InputRequiredRoundsExceededError as exc:
                raise ExpandRequestError(
                    ExpandFailure.INPUT_REQUIRED,
                    "MCP tool requires an unsupported input exchange; no continuation was sent. External effects may already exist.",
                ) from exc
            except Exception as exc:
                self.invalidate()
                raise ExpandRequestError(
                    ExpandFailure.RESULT_UNKNOWN,
                    "MCP call did not return a usable result; external effects may already exist. Inspect before retrying.",
                ) from exc

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        if self._lifetime is None:
            return ()

        async def finish() -> None:
            self._stop.set()
            assert self._lifetime is not None
            try:
                await asyncio.wait_for(asyncio.shield(self._lifetime), 5)
            except TimeoutError:
                if self._process is not None:
                    await self._process.close()
                self._lifetime.cancel()
                try:
                    await self._lifetime
                except asyncio.CancelledError:
                    pass
            self._lifetime = None
            self._directory = None

        joined = JoinedOperations()
        await joined.run_async(finish)
        joined.check_cancelled()
        return ()
