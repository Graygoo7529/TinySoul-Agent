"""Observation replay and WebSocket routes."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationLevel

from ...config import EndpointSettings
from ...engine import EndpointEngine
from ...errors import EndpointRequestError
from ..auth import websocket_cursor, websocket_mode, websocket_token_valid


def register_event_routes(
    app: FastAPI,
    engine: EndpointEngine,
    settings: EndpointSettings,
) -> None:
    @app.get("/v2/events")
    def events(
        after: int = Query(default=0, ge=0),
        mode: ObservationLevel = Query(default=ObservationLevel.NORMAL),
        limit: int = Query(default=200, ge=1, le=1000),
        instance_id: str | None = None,
    ) -> JsonObject:
        page = engine.events.replay(after=after, mode=mode, limit=limit, instance_id=instance_id)
        return {"instance_id": settings.instance_id, **page.to_json()}

    @app.websocket("/v2/events/ws")
    async def events_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            auth = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
            if not isinstance(auth, dict):
                await websocket.close(code=1008)
                return
            if not websocket_token_valid(auth.get("token"), settings):
                await websocket.close(code=1008)
                return
            after = websocket_cursor(auth.get("after", 0), "after")
            mode = websocket_mode(auth.get("mode", ObservationLevel.NORMAL.value))
            instance_id = auth.get("instance_id")
            if instance_id is not None and not isinstance(instance_id, str):
                await websocket.close(code=1008)
                return
            await websocket.send_json(
                {
                    "type": "authenticated",
                    "protocol_version": 2,
                    "instance_id": settings.instance_id,
                    "project_identity": settings.project_identity,
                    "next_sequence": engine.events.latest_sequence,
                }
            )
            page = await asyncio.to_thread(
                engine.events.replay, after=after, mode=mode, limit=200,
                instance_id=instance_id,
            )
            while True:
                if page.events or page.gap:
                    await websocket.send_json({"type": "events", "instance_id": settings.instance_id, **page.to_json()})
                else:
                    await websocket.send_json(
                        {"type": "heartbeat", "instance_id": settings.instance_id,
                         "next_sequence": page.next_sequence}
                    )
                after = page.next_sequence
                page = await asyncio.to_thread(
                    engine.events.wait_after, after=after, mode=mode,
                    timeout_seconds=settings.websocket_heartbeat_seconds,
                )
        except (WebSocketDisconnect, asyncio.TimeoutError):
            return
        except (EndpointRequestError, ValueError, UnicodeError):
            await websocket.close(code=1008)
