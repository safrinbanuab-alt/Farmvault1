from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self.active_connections = []
        self.router = APIRouter()

        @self.router.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self.connect(websocket)

            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                self.disconnect(websocket)
            except Exception:
                self.disconnect(websocket)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected")

    async def disconnect_all(self):
        for ws in self.active_connections[:]:
            try:
                await ws.close()
            except Exception:
                pass
        self.active_connections.clear()

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: dict):
        dead = []

        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def broadcast_json(self, data: dict):
        await self.broadcast(data)

    def get_connection_count(self):
        return len(self.active_connections)


ws_manager = WebSocketManager()