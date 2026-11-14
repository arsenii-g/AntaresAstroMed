import asyncio
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self.send_lock = asyncio.Lock()

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message):
        async def send(connection):
            try:
                await asyncio.wait_for(connection.send_json(message), timeout=0.5)
            except Exception:
                self.disconnect(connection)

        async with self.send_lock:
            await asyncio.gather(*(send(ws) for ws in tuple(self.active_connections)))
