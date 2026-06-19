"""
websocket.py
------------
WebSocket broadcaster and ``/ws/live`` endpoint.

Design
~~~~~~
``WebSocketBroadcaster`` is a singleton that holds the set of all active
WebSocket connections.  It is stored in ``app.state`` and never in a module
global.

Events are pushed from the inference callback (a regular OS thread) into the
asyncio event loop using ``asyncio.run_coroutine_threadsafe``.

Connection lifecycle
~~~~~~~~~~~~~~~~~~~~
1. Client connects to ``/ws/live``.
2. Server registers the connection and sends an immediate ``engine_*`` status event.
3. Pipeline callback fires ``broadcaster.broadcast_from_thread(event, loop)`` on every
   interesting frame event.
4. On disconnect / error, the connection is cleanly removed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.schemas import WSEvent, WSEventType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ---------------------------------------------------------------------------
# Broadcaster
# ---------------------------------------------------------------------------

class WebSocketBroadcaster:
    """
    Thread-safe registry of active WebSocket connections.

    All *_from_thread* methods are safe to call from any OS thread.
    All *async* methods must be awaited inside the asyncio event loop.
    """

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info(
            "WS client connected | total=%d | client=%s",
            len(self._connections),
            ws.client,
        )

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection (safe to call even if not registered)."""
        async with self._lock:
            self._connections.discard(ws)
        logger.info(
            "WS client disconnected | remaining=%d", len(self._connections)
        )

    # ------------------------------------------------------------------
    # Broadcast (async – call inside event loop)
    # ------------------------------------------------------------------

    async def broadcast(self, event: WSEvent) -> None:
        """
        Send *event* to **all** connected clients as a JSON string.

        Stale / closed connections are silently pruned.
        """
        if not self._connections:
            return

        payload = event.model_dump_json()
        dead: Set[WebSocket] = set()

        async with self._lock:
            targets = set(self._connections)

        for ws in targets:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
            except Exception as exc:  # noqa: BLE001
                logger.debug("WS send failed (marking dead): %s", exc)
                dead.add(ws)

        if dead:
            async with self._lock:
                self._connections -= dead
            logger.debug("Pruned %d dead WS connections", len(dead))

    async def send_to(self, ws: WebSocket, event: WSEvent) -> None:
        """Send *event* to a single WebSocket (used for handshake messages)."""
        try:
            await ws.send_text(event.model_dump_json())
        except Exception as exc:
            logger.debug("WS unicast failed: %s", exc)

    # ------------------------------------------------------------------
    # Thread-safe bridge
    # ------------------------------------------------------------------

    def broadcast_from_thread(
        self,
        event: WSEvent,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Schedule ``broadcast(event)`` on *loop* from any OS thread.

        This is the bridge between the VideoProcessor consumer thread and the
        async FastAPI event loop.  It is non-blocking from the caller's
        perspective.
        """
        if loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @staticmethod
    def make_event(event_type: str, payload: Dict[str, Any]) -> WSEvent:
        """Create a timestamped ``WSEvent``."""
        return WSEvent(
            type=event_type,
            payload=payload,
            timestamp=datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
        )

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# ---------------------------------------------------------------------------
# WebSocket route
# ---------------------------------------------------------------------------

@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """
    Push-based live event stream.

    Events sent to the client
    -------------------------
    * ``engine_started`` / ``engine_stopped`` – on engine lifecycle changes.
    * ``violation``      – every new violation event.
    * ``ocr_completed``  – when a plate read completes.
    * ``vehicle_tracked``– when a new ByteTrack ID is first observed.
    * ``frame_processed``– lightweight heartbeat on every Nth frame.
    * ``metrics``        – periodic system metrics snapshot.
    """
    broadcaster: WebSocketBroadcaster = websocket.app.state.broadcaster
    is_running: bool = getattr(websocket.app.state.pipeline, "is_running", False)

    await broadcaster.connect(websocket)

    # Send initial status on connection
    await broadcaster.send_to(
        websocket,
        broadcaster.make_event(
            WSEventType.ENGINE_STARTED if is_running else WSEventType.ENGINE_STOPPED,
            {"message": "Connected to Gridlock live stream"},
        ),
    )

    try:
        while True:
            # Keep the connection alive by waiting for any client message
            # (clients typically send a ping / heartbeat).
            data = await websocket.receive_text()
            logger.debug("WS received from client: %s", data[:120])

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected cleanly")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        await broadcaster.disconnect(websocket)
