"""MCP discovery and call facade; all four actions consume one owner directory."""

from __future__ import annotations

from base64 import b64decode
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject, JsonValue, dumps_json
from tinysoul.plugins.workspace import WorkspaceEngine
from tinysoul.plugins.workspace.inspection.models import WorkspaceBundleWrite
from .config import ExpandSettings, validate_expand_bindings
from .failures import ExpandFailure, ExpandRequestError

if TYPE_CHECKING:
    from .mcp.client import MCPConnection, ToolDirectory
    from tinysoul.infra.json.schema import JSONSchema


@dataclass(frozen=True)
class ToolDefinition:
    server_id: str
    name: str
    definition: JsonObject
    inputs: JSONSchema | None
    output: JSONSchema | None
    problem: str = ""

    @property
    def identity(self) -> JsonObject:
        return {"server_id": self.server_id, "tool_name": self.name}

    def summary(self) -> JsonObject:
        description = self.definition.get("description", "")
        return {
            **self.identity,
            "description": str(description)[:1000],
            "callable": not self.problem,
            **({"unavailable": self.problem} if self.problem else {}),
        }

    def describe(self) -> JsonObject:
        return {
            **self.summary(),
            **({"definition": self.definition} if not self.problem else {}),
        }


@dataclass(frozen=True)
class Discovery:
    tools: tuple[ToolDefinition, ...]
    servers: tuple[JsonObject, ...]


@dataclass(frozen=True)
class _Page:
    items: tuple[JsonObject, ...]
    offset: int
    expires: float
    kind: str
    sources: tuple[tuple[str, ToolDirectory | None], ...]


class ExpandEngine:
    def __init__(
        self,
        settings: ExpandSettings,
        *,
        root: Path,
        workspace: WorkspaceEngine,
        environment: Mapping[str, str],
    ) -> None:
        self.settings, self._workspace = settings, workspace
        self._connections: dict[str, MCPConnection] = {}
        self._pages: dict[str, _Page] = {}
        self._definitions: dict[
            str, tuple[ToolDirectory, tuple[ToolDefinition, ...]]
        ] = {}
        validate_expand_bindings(settings, environment)
        enabled = tuple(server for server in settings.servers if server.enabled)
        if enabled:
            from .mcp.client import MCPConnection

            for server in enabled:
                self._connections[server.server_id] = MCPConnection(
                    server, settings, root=root, environment=environment
                )

    @property
    def available(self) -> bool:
        return bool(self._connections)

    async def discover(self, server_ids: tuple[str, ...] | None = None) -> Discovery:
        from tinysoul.infra.json.schema import JSONSchema, JSONSchemaError

        tools: list[ToolDefinition] = []
        servers: list[JsonObject] = []
        identities = (
            tuple(dict.fromkeys(server_ids))
            if server_ids is not None
            else tuple(self._connections)
        )
        for identity in identities:
            connection = self._connections.get(identity)
            if connection is None:
                servers.append({"server_id": identity, "status": "unavailable"})
                continue
            status: JsonObject = {
                "server_id": identity,
                "description": connection.server.description[:1000],
            }
            try:
                directory = await connection.directory()
            except ExpandRequestError as exc:
                servers.append(
                    {**status, "status": "unavailable", "reason": exc.reason.value}
                )
                continue
            cached = self._definitions.get(identity)
            if cached is not None and cached[0] is directory:
                tools.extend(cached[1])
                servers.append(
                    {**status, "status": "available", "tool_count": len(cached[1])}
                )
                continue
            start = len(tools)
            count = 0
            for definition in directory.tools:
                name = definition.get("name")
                if not isinstance(name, str) or not connection.server.allows(name):
                    continue
                count += 1
                inputs = output = None
                problem = ""
                try:
                    if (
                        len(dumps_json(definition))
                        > self.settings.max_inline_chars - 1024
                    ):
                        raise JSONSchemaError(
                            "Tool definition exceeds the complete-definition limit."
                        )
                    input_schema, output_schema = (
                        definition.get("inputSchema"),
                        definition.get("outputSchema"),
                    )
                    if not isinstance(input_schema, dict) or (
                        output_schema is not None
                        and not isinstance(output_schema, dict)
                    ):
                        raise JSONSchemaError("Tool schemas must be objects.")
                    inputs = JSONSchema(input_schema)
                    output = (
                        JSONSchema(output_schema)
                        if isinstance(output_schema, dict)
                        else None
                    )
                except JSONSchemaError:
                    problem = "unsupported_schema"
                tools.append(
                    ToolDefinition(identity, name, definition, inputs, output, problem)
                )
            servers.append({**status, "status": "available", "tool_count": count})
            self._definitions[identity] = (directory, tuple(tools[start:]))
        return Discovery(tuple(tools), tuple(servers))

    def page(
        self,
        items: tuple[JsonObject, ...] = (),
        *,
        servers: tuple[JsonObject, ...] = (),
        cursor: str | None = None,
        kind: str,
        max_chars: int | None = None,
    ) -> JsonObject:
        limit = (
            min(max_chars, self.settings.max_inline_chars)
            if max_chars is not None
            else self.settings.max_inline_chars
        )
        now = monotonic()
        self._pages = {
            key: page for key, page in self._pages.items() if page.expires > now
        }
        offset = 0
        sources = tuple(
            (
                str(server["server_id"]),
                self._connections[str(server["server_id"])].directory_identity,
            )
            for server in servers
            if str(server["server_id"]) in self._connections
        )
        if cursor is not None:
            page = self._pages.get(cursor)
            if (
                page is None
                or page.kind != kind
                or any(
                    self._connections[identity].directory_identity is not directory
                    for identity, directory in page.sources
                )
            ):
                raise ExpandRequestError(
                    ExpandFailure.INVALID_REQUEST,
                    "Directory page expired; describe the scope again.",
                )
            items, offset = page.items, page.offset
            sources = page.sources
        else:
            items = (
                *({"server": server} for server in servers),
                *({"tool": item} for item in items),
            )
        selected: list[JsonValue] = []
        server_page: list[JsonValue] = []
        size = 128
        while offset < len(items) and len(selected) < self.settings.page_size:
            item = items[offset]
            item_size = len(dumps_json(item))
            if size + item_size > limit:
                if not selected and not server_page:
                    raise ExpandRequestError(
                        ExpandFailure.CAPACITY,
                        "Directory item exceeds response capacity.",
                    )
                break
            if "server" in item:
                server_page.append(item["server"])
            else:
                selected.append(item["tool"])
            size += item_size
            offset += 1
        next_page: str | None = None
        if offset < len(items):
            if len(self._pages) >= 16:
                del self._pages[next(iter(self._pages))]
            next_page = uuid4().hex
            self._pages[next_page] = _Page(items, offset, now + 300, kind, sources)
        return {"servers": server_page, "tools": selected, "next_page": next_page}

    async def call(
        self,
        server_id: str,
        name: str,
        arguments: JsonObject,
        *,
        operations: JoinedOperations,
    ) -> JsonObject:
        from tinysoul.infra.json.schema import (
            JSONSchemaError,
            JSONSchemaValidationError,
        )

        discovered = await self.discover((server_id,))
        tool = next((item for item in discovered.tools if item.name == name), None)
        if tool is None:
            raise ExpandRequestError(
                ExpandFailure.UNAVAILABLE,
                "Tool is unavailable or excluded by server policy.",
            )
        if tool.problem or tool.inputs is None:
            raise ExpandRequestError(
                ExpandFailure.SCHEMA,
                "Tool definition is unsupported or exceeds its bound.",
            )
        try:
            tool.inputs.validate(arguments)
        except JSONSchemaValidationError as exc:
            raise ExpandRequestError(
                ExpandFailure.ARGUMENTS, "Arguments do not satisfy the tool definition."
            ) from exc
        except JSONSchemaError as exc:
            raise ExpandRequestError(
                ExpandFailure.SCHEMA, "Tool schema could not be resolved."
            ) from exc
        result = await self._connections[server_id].call(name, arguments)
        structured = result.get("structuredContent")
        if tool.output is not None and not result.get("isError"):
            try:
                tool.output.validate(structured)
            except JSONSchemaError as exc:
                raise ExpandRequestError(
                    ExpandFailure.REMOTE,
                    "Tool returned output that does not satisfy its schema.",
                ) from exc
        return await self._project_result(tool, result, operations)

    async def _project_result(
        self, tool: ToolDefinition, result: JsonObject, operations: JoinedOperations
    ) -> JsonObject:
        serialized = dumps_json(result)
        if len(serialized.encode()) > self.settings.max_result_bytes:
            raise ExpandRequestError(
                ExpandFailure.CAPACITY,
                "Tool result exceeds the configured output bound; effects may already exist.",
            )
        prefix = f"workspace:mcp/{uuid4().hex}"
        writes: list[WorkspaceBundleWrite] = []
        content: list[JsonValue] = []
        blocks = result.get("content", [])
        if not isinstance(blocks, list):
            raise ExpandRequestError(ExpandFailure.REMOTE, "Tool content is invalid.")
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                text = block.get("text", "")
                if not isinstance(text, str):
                    continue
                if result.get("structuredContent") is not None:
                    try:
                        if json.loads(text) == result["structuredContent"]:
                            continue
                    except ValueError:
                        pass
                if len(text) <= self.settings.max_inline_chars:
                    content.append({"type": "text", "text": text})
                    continue
                link = f"{prefix}/{index}.txt"
                writes.append(WorkspaceBundleWrite(link, text.encode()))
                content.append({"link": link, "summary": text[:500]})
            elif kind in {"image", "audio", "resource"}:
                resource = block.get("resource") if kind == "resource" else block
                if not isinstance(resource, dict):
                    continue
                encoded, text = (
                    resource.get("data", resource.get("blob")),
                    resource.get("text"),
                )
                try:
                    data = (
                        text.encode()
                        if isinstance(text, str)
                        else b64decode(encoded, validate=True)
                        if isinstance(encoded, str)
                        else b""
                    )
                except ValueError as exc:
                    raise ExpandRequestError(
                        ExpandFailure.REMOTE, "Tool returned invalid embedded content."
                    ) from exc
                suffix = {
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "audio/wav": ".wav",
                    "audio/mpeg": ".mp3",
                }.get(
                    str(resource.get("mimeType")),
                    ".txt" if isinstance(text, str) else ".bin",
                )
                link = f"{prefix}/{index}{suffix}"
                writes.append(WorkspaceBundleWrite(link, data))
                content.append(
                    {
                        "link": link,
                        "media_type": resource.get(
                            "mimeType", "application/octet-stream"
                        ),
                    }
                )
            elif kind == "resource_link":
                content.append(
                    {
                        "type": "external_resource",
                        "uri": block.get("uri"),
                        "name": block.get("name"),
                    }
                )
        payload: JsonObject = {
            **tool.identity,
            "is_error": result.get("isError", False),
            "content": content,
        }
        if result.get("structuredContent") is not None:
            payload["structured"] = result["structuredContent"]
        if len(dumps_json(payload)) > self.settings.max_inline_chars:
            link = f"{prefix}/result.json"
            writes.append(WorkspaceBundleWrite(link, dumps_json(payload).encode()))
            payload = {
                **tool.identity,
                "is_error": result.get("isError", False),
                "result_link": link,
            }
        if writes:
            await operations.run(lambda: self._workspace.write_bundle(tuple(writes)))
        return payload

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        diagnostics: list[CleanupDiagnostic] = []
        for connection in self._connections.values():
            diagnostics.extend(await connection.close())
        self._pages.clear()
        self._definitions.clear()
        return tuple(diagnostics)
