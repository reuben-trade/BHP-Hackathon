from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, List
import asyncio
import json
from datetime import datetime
from models import MooringTerminal, Berth, Bollard, Hook

app = FastAPI(
    title="BHP Mooring System Backend API",
    description="Backend API for Mooring System Monitoring",
    version="1.0.0"
)

# Store latest data
current_data: Optional[MooringTerminal] = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send current data immediately upon connection
        if current_data:
            await websocket.send_json(current_data.dict())

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


manager = ConnectionManager()
@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "BHP Mooring Backend API",
        "version": "1.0.0",
        "active_connections": len(manager.active_connections)
    }


@app.post("/receive/")
async def receive(data: MooringTerminal):
    """
    Receive mooring system data.
    Automatically validates structure and provides rich data access.
    """
    global current_data

    # Add timestamp if not provided
    if data.timestamp is None:
        data.timestamp = datetime.now()

    current_data = data

    # Process tension data for each berth
    analysis = {}
    for berth in data.berths:
        if berth.has_ship:
            berth_analysis = {
                "ship_name": berth.ship.name,
                "vessel_id": berth.ship.vesselId,
                "total_tension": berth.total_berth_tension,
                "tensions_by_bollard": berth.get_tensions_by_bollard(),
                "tensions_by_line_type": berth.get_all_tensions_by_line_type(),
                "active_bollards": len([b for b in berth.bollards if b.active_hook_count > 0]),
                "total_bollards": len(berth.bollards),
                "active_radars": len(berth.active_radars)
            }
            analysis[berth.name] = berth_analysis

    # Broadcast to connected clients
    await broadcast_data(data.model_dump_json())

    return {
        "status": "received",
        "terminal": data.name,
        "timestamp": data.timestamp,
        "analysis": analysis
    }


@app.get("/terminal/status")
async def get_terminal_status():
    """Get current terminal status."""
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    return {
        "terminal": current_data.name,
        "timestamp": current_data.timestamp,
        "total_berths": len(current_data.berths),
        "active_berths": len(current_data.active_berths),
        "berths": [
            {
                "name": berth.name,
                "has_ship": berth.has_ship,
                "ship_name": berth.ship.name if berth.ship else None,
                "total_tension": berth.total_berth_tension
            }
            for berth in current_data.berths
        ]
    }


@app.get("/berth/{berth_name}")
async def get_berth_details(berth_name: str):
    """Get detailed information for a specific berth."""
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    berth = current_data.get_berth_by_name(berth_name)
    if berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {berth_name} not found")

    return berth.model_dump_json()


@app.get("/berth/{berth_name}/tensions")
async def get_berth_tensions(berth_name: str):
    """
    Get detailed tension analysis for a berth.
    Perfect for visualization!
    """
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    berth = current_data.get_berth_by_name(berth_name)
    if berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {berth_name} not found")

    # Build comprehensive tension data
    bollard_data = []
    for bollard in berth.bollards:
        hooks_data = []
        for hook in bollard.hooks:
            hooks_data.append({
                "name": hook.name,
                "tension": hook.tension,
                "status": hook.tension_status,
                "faulted": hook.faulted,
                "line_type": hook.attachedLine,
                "is_active": hook.is_active
            })

        bollard_data.append({
            "name": bollard.name,
            "total_tension": bollard.total_tension,
            "active_hooks": bollard.active_hook_count,
            "total_hooks": bollard.hook_count,
            "tensions_by_line": bollard.get_tensions_by_line(),
            "hooks": hooks_data
        })

    return {
        "berth": berth_name,
        "ship": berth.ship.model_dump_json() if berth.ship else None,
        "total_tension": berth.total_berth_tension,
        "tensions_by_line_type": berth.get_all_tensions_by_line_type(),
        "bollards": bollard_data,
        "summary": {
            "total_bollards": len(berth.bollards),
            "active_bollards": len([b for b in berth.bollards if b.active_hook_count > 0]),
            "total_hooks": berth.hookCount,
            "active_hooks": sum(b.active_hook_count for b in berth.bollards)
        }
    }


@app.get("/berth/{berth_name}/bollard/{bollard_name}")
async def get_bollard_details(berth_name: str, bollard_name: str):
    """Get detailed information for a specific bollard."""
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    berth = current_data.get_berth_by_name(berth_name)
    if berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {berth_name} not found")

    bollard = berth.get_bollard_by_name(bollard_name)
    if bollard is None:
        raise HTTPException(status_code=404, detail=f"Bollard {bollard_name} not found")

    return {
        "bollard": bollard.name,
        "total_tension": bollard.total_tension,
        "tensions_by_line": bollard.get_tensions_by_line(),
        "hooks": [
            {
                "name": hook.name,
                "tension": hook.tension,
                "status": hook.tension_status,
                "line_type": hook.attachedLine,
                "faulted": hook.faulted
            }
            for hook in bollard.hooks
        ]
    }


@app.get("/visualization/{berth_name}")
async def get_visualization_data(berth_name: str):
    """
    Get data formatted specifically for ship layout visualization.
    Returns bollard positions with tension data for each line type.
    """
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    berth = current_data.get_berth_by_name(berth_name)
    if berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {berth_name} not found")

    # Format data for visualization
    viz_data = {
        "berth": berth_name,
        "ship": berth.ship.model_dump_json() if berth.ship else None,
        "bollards": []
    }

    for idx, bollard in enumerate(berth.bollards):
        bollard_viz = {
            "id": bollard.name,
            "index": idx,
            "position": idx / len(berth.bollards),  # Normalized position (0-1)
            "total_tension": bollard.total_tension,
            "lines": []
        }

        # Group by line type for visualization
        tensions_by_line = bollard.get_tensions_by_line()
        for line_type, tensions in tensions_by_line.items():
            bollard_viz["lines"].append({
                "type": line_type,
                "tensions": tensions,
                "total": sum(tensions),
                "average": sum(tensions) / len(tensions) if tensions else 0,
                "max": max(tensions) if tensions else 0,
                "hook_count": len(tensions)
            })

        viz_data["bollards"].append(bollard_viz)

    # Add summary statistics
    viz_data["summary"] = {
        "total_tension": berth.total_berth_tension,
        "line_type_totals": berth.get_all_tensions_by_line_type(),
        "bollard_count": len(berth.bollards),
        "active_bollard_count": len([b for b in berth.bollards if b.active_hook_count > 0])
    }

    return viz_data


@app.get("/stream")
async def stream_data():
    """Live stream endpoint - Server-Sent Events (SSE)."""

    async def event_generator():
        queue = asyncio.Queue()
        subscribers.append(queue)

        try:
            # Send initial data
            if current_data:
                yield f"data: {json.dumps(current_data.model_dump_json())}\n\n"

            # Keep connection alive and send new data
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            subscribers.remove(queue)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


async def broadcast_data(data: dict):
    """Send data to all connected subscribers."""
    for queue in subscribers:
        await queue.put(data)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)