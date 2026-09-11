from __future__ import annotations

import json
import logging
from typing import Dict, List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict):
        stale = []
        msg_str = json.dumps(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(msg_str)
            except Exception:
                stale.append(connection)

        for s in stale:
            self.active_connections.discard(s)


ws_manager = ConnectionManager()


@router.websocket("/collaborate")
async def websocket_collaborate_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                # Broadcast events (e.g. lock acquired, draft saved) to all peers
                event_type = payload.get("event")
                if event_type in ["LOCK_ACQUIRED", "LOCK_RELEASED", "DRAFT_SAVED", "STATUS_CHANGED"]:
                    await ws_manager.broadcast(payload)
                elif event_type == "PING":
                    await websocket.send_text(json.dumps({"event": "PONG"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket error: %s", e)
        ws_manager.disconnect(websocket)
