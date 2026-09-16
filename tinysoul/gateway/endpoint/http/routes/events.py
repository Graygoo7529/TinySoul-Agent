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
    @app.get("/v1/events")
    def events(
        after: int = Query(default=0, ge=0),
        mode: ObservationLevel = Query(default=ObservationLevel.NORMAL),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> JsonObject:
        return engine.events.replay(after=after, mode=mode, limit=limit).to_json()

    @app.websocket("/v1/events/ws")
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
            await websocket.send_json(
                {
                    "type": "authenticated",
                    "protocol_version": 1,
                    "instance_id": settings.instance_id,
                    "project_identity": settings.project_identity,
                    "next_sequence": engine.events.latest_sequence,
                }
            )
            while True:
                page = await asyncio.to_thread(
                    engine.events.wait_after,
                    after=after,
                    mode=mode,
                    timeout_seconds=settings.websocket_heartbeat_seconds,
                )
                if page.events or page.gap:
                    await websocket.send_json({"type": "events", **page.to_json()})
                else:
                    await websocket.send_json(
                        {"type": "heartbeat", "next_sequence": page.next_sequence}
                    )
                after = page.next_sequence
        except (WebSocketDisconnect, asyncio.TimeoutError):
            return
        except EndpointRequestError:
            await websocket.close(code=1008)
