"""External connections and sessions; delegated work belongs to the shared Registry."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from tinysoul.prompts.plugins.capabilities import subagent as prompt_text
from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.infra.process import ManagedProcessCloseError
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.plugins.workspace.services import WorkspaceExecutionPort
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tinysoul.runtime.sources import EventSink, SourceState, SourceStatus

from .config import AgentTarget, SubagentSettings, validate_subagent_bindings
from .failures import SubagentFailure, SubagentRequestError

if TYPE_CHECKING:
    from .acp.connection import ACPConnection
    from .jobs.backend import ACPJobBackend


class ConnectionState(StrEnum):
    UNAVAILABLE = "unavailable"
    BUSY = "busy"
    READY = "ready"


@dataclass
class _Connection:
    identity: str
    target: AgentTarget
    cwd: Path
    cwd_link: str
    profile: str
    owner_turn: str | None
    client: ACPConnection
    job_id: str | None = None


class SubagentEngine:
    def __init__(
        self,
        settings: SubagentSettings,
        *,
        jobs: JobRegistry,
        workspace: WorkspaceExecutionPort,
        environment: Mapping[str, str],
    ) -> None:
        self.settings, self.jobs, self._workspace = settings, jobs, workspace
        self._targets = {
            target.agent_id: target for target in settings.agents if target.enabled
        }
        self._connections: dict[str, _Connection] = {}
        self._environments = validate_subagent_bindings(settings, environment)
        self._lock = asyncio.Lock()
        self._publish: EventSink | None = None

    @property
    def available(self) -> bool:
        return bool(self._targets)

    @property
    def status(self) -> SourceStatus:
        return SourceStatus(
            "subagent",
            SourceState.RUNNING if self._publish is not None else SourceState.STOPPED,
            topics=("subagent.connections",),
        )

    async def start(self, publish: EventSink) -> None:
        self._publish = publish

    async def stop(self) -> None:
        self._publish = None

    def agents(self) -> JsonObject:
        return {
            "agents": [
                {"agent_id": item.agent_id, "description": item.description}
                for item in self._targets.values()
            ]
        }

    def connections(self, turn_id: str | None = None) -> JsonObject:
        return {
            "connections": [
                {
                    "connection_id": item.identity,
                    "agent_id": item.target.agent_id,
                    "cwd_link": item.cwd_link,
                    "state": ConnectionState.UNAVAILABLE.value
                    if item.client.closed
                    else ConnectionState.BUSY.value
                    if item.job_id
                    else ConnectionState.READY.value,
                    "active_job_id": item.job_id,
                    "turn_id": item.owner_turn,
                }
                for item in self._connections.values()
                if turn_id is None or item.owner_turn == turn_id
            ]
        }

    async def _changed(self, turn_id: str) -> None:
        if self._publish is not None:
            await self._publish(
                EnvironmentEvent(
                    EventKind.EVENT,
                    {},
                    target_id=turn_id,
                    topic="subagent.connections",
                    source="subagent",
                )
            )

    def status_view(self) -> JsonObject:
        return {
            "targets": [
                {
                    "agent_id": item.agent_id,
                    "description": item.description,
                    "enabled": item.enabled,
                }
                for item in self.settings.agents
            ],
            **self.connections(),
        }

    async def connect(
        self, turn_id: str, profile: str, agent_id: str, cwd_link: str = ""
    ) -> JsonObject:
        from .acp.connection import ACPConnection

        async with self._lock:
            target = self._targets.get(agent_id)
            if target is None:
                raise SubagentRequestError(
                    SubagentFailure.UNAVAILABLE,
                    prompt_text.CONFIGURED_AGENT_TARGET_IS_UNAVAILABLE,
                )
            for item in self._connections.values():
                if (
                    item.owner_turn is None
                    and item.target == target
                    and item.profile == profile
                    and (not cwd_link or item.cwd_link == cwd_link)
                    and not item.client.closed
                ):
                    try:
                        await item.client.new_session(item.cwd)
                    except Exception as exc:
                        await item.client.close()
                        raise SubagentRequestError(
                            SubagentFailure.UNAVAILABLE,
                            prompt_text.EXTERNAL_AGENT_SESSION_COULD_NOT_BE_CREATED,
                        ) from exc
                    item.owner_turn = turn_id
                    await self._changed(turn_id)
                    return {
                        "connection_id": item.identity,
                        "agent_id": agent_id,
                        "cwd_link": item.cwd_link,
                    }
            for identity, item in tuple(self._connections.items()):
                if item.client.closed or (
                    len(self._connections) >= self.settings.max_connections
                    and item.owner_turn is None
                ):
                    await item.client.close()
                    del self._connections[identity]
            if len(self._connections) >= self.settings.max_connections:
                raise SubagentRequestError(
                    SubagentFailure.BUSY,
                    prompt_text.CONNECTION_CAPACITY_EXCEEDED,
                )
            identity = f"connection_{uuid4().hex}"
            operations = JoinedOperations()
            cwd, link = await operations.run(
                lambda: self._workspace.prepare_external_cwd(
                    identity, cwd_link=cwd_link
                )
            )
            operations.check_cancelled()
            try:
                client = await ACPConnection.connect(
                    target, self.settings, cwd, self._environments[agent_id]
                )
            except ManagedProcessCloseError:
                raise
            except Exception as exc:
                raise SubagentRequestError(
                    SubagentFailure.UNAVAILABLE,
                    prompt_text.EXTERNAL_AGENT_CONNECTION_FAILED,
                ) from exc
            self._connections[identity] = _Connection(
                identity, target, cwd, link, profile, turn_id, client
            )
            await self._changed(turn_id)
            return {"connection_id": identity, "agent_id": agent_id, "cwd_link": link}

    def _owned(self, turn_id: str, connection_id: str) -> _Connection:
        item = self._connections.get(connection_id)
        if item is None or item.owner_turn != turn_id:
            raise SubagentRequestError(
                SubagentFailure.INVALID_REQUEST,
                prompt_text.CONNECTION_IS_UNAVAILABLE_IN_THIS_TURN,
            )
        return item

    async def delegate(self, turn_id: str, connection_id: str, brief: str) -> str:
        from .jobs.backend import ACPJobBackend

        async with self._lock:
            item = self._owned(turn_id, connection_id)
            if item.job_id is not None or item.client.closed:
                raise SubagentRequestError(
                    SubagentFailure.BUSY, prompt_text.CONNECTION_IS_BUSY_OR_CLOSED
                )
            if not brief.strip() or len(brief) > self.settings.max_brief_chars:
                raise SubagentRequestError(
                    SubagentFailure.INVALID_REQUEST,
                    prompt_text.DELEGATION_REQUIRES_A_BOUNDED_NON_EMPTY_BRIEF,
                )

            async def closed() -> None:
                item.job_id = None
                await self._changed(turn_id)

            async def create(job_id: str) -> ACPJobBackend:
                backend = ACPJobBackend(
                    job_id,
                    item.client,
                    brief,
                    settings=self.settings,
                    workspace=self._workspace,
                    closed=closed,
                )
                item.job_id = job_id
                return backend

            backend = await self.jobs.start(turn_id, ACPJobBackend.kind, create)
            await self._changed(turn_id)
            return backend.job_id

    def backend(self, turn_id: str, job_id: str) -> ACPJobBackend:
        from .jobs.backend import ACPJobBackend

        return self.jobs.backend(turn_id, job_id, ACPJobBackend)

    async def prepare_brief(
        self, brief: str, links: tuple[str, ...], operations: JoinedOperations
    ) -> str:
        blocks = [brief]
        for link in links:
            if not link.startswith("workspace:"):
                raise SubagentRequestError(
                    SubagentFailure.INVALID_REQUEST,
                    prompt_text.WORKSPACE_REFERENCE_REQUIRED,
                )
            source = await operations.run(
                lambda: self._workspace.read_text(
                    link, max_chars=self.settings.max_brief_chars
                )
            )
            if source.truncated:
                raise SubagentRequestError(
                    SubagentFailure.INVALID_REQUEST,
                    prompt_text.REFERENCE_INPUT_LIMIT_EXCEEDED,
                )
            blocks.append(prompt_text.delegation_reference(link=link, text=source.text))
        result = "\n\n".join(blocks)
        if len(result) > self.settings.max_brief_chars:
            raise SubagentRequestError(
                SubagentFailure.INVALID_REQUEST,
                prompt_text.DELEGATION_INPUT_EXCEEDS_ITS_BOUND,
            )
        return result

    async def disconnect(self, turn_id: str, connection_id: str) -> None:
        async with self._lock:
            item = self._owned(turn_id, connection_id)
            if item.job_id is not None:
                raise SubagentRequestError(
                    SubagentFailure.BUSY,
                    prompt_text.ACTIVE_JOB_BLOCKS_DISCONNECTION,
                )
            await item.client.close()
            del self._connections[connection_id]
            await self._changed(turn_id)

    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        async with self._lock:
            for identity, item in tuple(self._connections.items()):
                if item.owner_turn != turn_id:
                    continue
                if item.job_id is not None:
                    raise SubagentRequestError(
                        SubagentFailure.BUSY,
                        prompt_text.JOBS_MUST_CLOSE_BEFORE_THEIR_SESSIONS,
                    )
                await item.client.release_session()
                item.owner_turn = None
                if item.client.closed:
                    del self._connections[identity]
        return ()

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        return await self.release_day()

    async def release_day(self) -> tuple[CleanupDiagnostic, ...]:
        """Drop idle connections bound to the old Workspace before its archive."""
        diagnostics: list[CleanupDiagnostic] = []
        async with self._lock:
            for item in self._connections.values():
                diagnostics.extend(await item.client.close())
            self._connections.clear()
        return tuple(diagnostics)
