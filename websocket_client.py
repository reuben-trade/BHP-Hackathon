from typing import List
from fastapi import WebSocket

from models import MooringTerminal


class ConnectionManager:
    def __init__(self, current_data: MooringTerminal):
        self.current_data = current_data
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send current data immediately upon connection
        if self.current_data:
            await websocket.send_json(self.current_data.model_dump_json())

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Broadcast to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)
