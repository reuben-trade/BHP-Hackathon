from collections import deque
import math
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from typing import Optional, Dict, List
import asyncio
import json
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnect

from models import MooringTerminal, Berth, Bollard, Hook

DEFAULT_ANGLE = 0
DEFAULT_SHIP_W = 20
DEFAULT_SHIP_L = 80

app = FastAPI(
    title="BHP Mooring System Backend API",
    description="Backend API for Mooring System Monitoring",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Store latest data
current_data: Optional[MooringTerminal] = None
mooring_db = deque(maxlen=1000)

#Safety threshold to clear from line
SAFETY_LIMIT = 90

RADAR_SPACING = 100.0  # metres between the two radars along the ship

def calculate_orientation_from_two_radars(berth) -> float:
    """
    Calculate ship orientation using exactly 2 radar readings.

    Assumptions:
    - We use the first and last ACTIVE radars in berth.radars
    - Distance between those two radars along the ship = 100m
    - 0 rad  = parallel to quay
    - >0 rad = second radar further from quay than first
    """

    # Pick active radars with a valid distance
    active_radars = [
        r for r in berth.radars
        if r.distanceStatus == "ACTIVE" and r.shipDistance is not None
    ]

    # Need at least 2, otherwise fall back
    if len(active_radars) < 2:
        return DEFAULT_ANGLE

    # Use exactly two: first and last active
    r1 = active_radars[0]
    r2 = active_radars[-1]

    d1 = r1.shipDistance
    d2 = r2.shipDistance

    # θ = atan2(Δdistance, along-ship spacing)
    angle = math.atan2(d2 - d1, RADAR_SPACING)
    return angle

def compute_hook_colours_for_berth(berth) -> Dict[tuple, str]:
    """
    Compute a colour for each hook in a berth based on:
    - all hooks in each bollard (group = bollard)
    - ship orientation angle from 2 radars (distance 100m)
    - same logic as your standalone colour script

    Returns:
        colours: dict[(berth_name, hook_name)] = 'red' | 'green' | 'yellow' | 'black'
    """
    angle = calculate_orientation_from_two_radars(berth)
    ANGLE_THRESH = math.pi / 180  # 1 degree

    groups: List[List[float]] = []      # list of tension lists
    group_hooks: List[List[Hook]] = []  # parallel list of hook lists

    # Build groups: each bollard → one group with ALL its hooks
    for bollard in berth.bollards:
        hooks = bollard.hooks
        if not hooks:
            continue

        tensions = []
        for hook in hooks:
            if hook.tension is None or hook.faulted:
                t = 0.0
            else:
                t = float(hook.tension)
            tensions.append(t)

        groups.append(tensions)
        group_hooks.append(hooks)

    if not groups:
        return {}

    num_groups = len(groups)
    colours: Dict[tuple, str] = {}

    for group_idx, (group, hooks) in enumerate(zip(groups, group_hooks), start=1):
        arr = np.array(group, dtype=float)
        stdev = float(np.std(arr))
        mean = float(np.mean(arr))


        group_desired: List[float] = []
        alarm = False

        # First half of bollards = "back", second half = "front"
        is_back_group = group_idx <= num_groups / 2

        for line in group:
            desiredLine = 0.0

            # Equalise within group if spread is large
            if stdev > 10:
                desiredLine -= line - mean

            # Angle contribution with back/front reversal
            if angle > ANGLE_THRESH:
                # bow further from quay than stern
                desiredLine += -5 if is_back_group else 5
            elif angle < -ANGLE_THRESH:
                # bow closer to quay than stern
                desiredLine += 5 if is_back_group else -5

            # Clamp so we don't exceed safety
            if desiredLine > SAFETY_LIMIT - line:
                desiredLine = SAFETY_LIMIT - line

            # Alarm if any line already above safety
            if line > SAFETY_LIMIT:
                alarm = True

            group_desired.append(desiredLine)

        # If any rope is unsafe, whole group is black, desired = 0
        if alarm:
            for hook in hooks:
                colours[(berth.name, hook.name)] = "black"
            continue

        # Otherwise, red / yellow / green per hook
        for hook, d in zip(hooks, group_desired):
            if d > 1.5:
                colour = "red"
            elif d < -1.5:
                colour = "green"
            else:
                colour = "yellow"

            colours[(berth.name, hook.name)] = colour

    return colours


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send current data immediately upon connection
        if current_data:
            await websocket.send_json(current_data.model_dump_json())

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
    mooring_db.append(data)

    await manager.broadcast(data.model_dump_json())

    return {"status": "received", "timestamp": data.timestamp}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Websocket endpoint - clients connect to receive json loads"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/ships")
async def get_data():
    return {"data": mooring_db[-1]}


@app.get("/ships/{ship_id}")
async def get_ship_data(ship_id: str):
    """
    Get the most recent data for a specific ship by vessel ID.
    Returns berth information, bollard tensions, and ship details.
    """
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    # Search through all berths for the ship
    for berth in current_data.berths:
        if berth.ship and berth.ship.vesselId == ship_id:
            # --- NEW: compute colours for this berth ---
            hook_colours = compute_hook_colours_for_berth(berth)
            # -------------------------------------------

            # Build comprehensive ship data
            bollard_data = []
            for bollard in berth.bollards:
                hooks_data = []
                for hook in bollard.hooks:
                    if hook.tension is not None:  # Only include active hooks
                        colour = hook_colours.get((berth.name, hook.name))
                        hooks_data.append({
                            "name": hook.name,
                            "tension": hook.tension,
                            "status": hook.tension_status,
                            "faulted": hook.faulted,
                            "line_type": hook.attachedLine,
                            "is_active": hook.is_active,
                            "colour": colour,      # ← ADDED
                        })

                if hooks_data:  # Only include bollards with active hooks
                    bollard_data.append({
                        "name": bollard.name,
                        "total_tension": bollard.total_tension,
                        "active_hooks": bollard.active_hook_count,
                        "tensions_by_line": bollard.get_tensions_by_line(),
                        "hooks": hooks_data
                    })

            orientation_angle = calculate_orientation_from_two_radars(berth)

            return {
                "ship": {
                    "name": berth.ship.name,
                    "vessel_id": berth.ship.vesselId,
                    "ship_width": DEFAULT_SHIP_W,
                    "ship_length": DEFAULT_SHIP_L,
                },
                "berth": berth.name,
                "terminal": current_data.name,
                "timestamp": current_data.timestamp.isoformat() if current_data.timestamp else None,
                "statistics": {
                    "orientation_angle": orientation_angle,             # radians
                    "orientation_angle_deg": math.degrees(orientation_angle),
                    "total_tension": berth.total_berth_tension,
                    "tensions_by_line_type": berth.get_all_tensions_by_line_type(),
                    "active_bollards": len([b for b in berth.bollards if b.active_hook_count > 0]),
                    "total_bollards": len(berth.bollards),
                    "active_hooks": sum(b.active_hook_count for b in berth.bollards)
                },
                "bollards": bollard_data,
                "radars": [
                    {
                        "name": radar.name,
                        "distance": radar.shipDistance,
                        "distance_change": radar.distanceChange,
                        "status": radar.distanceStatus,
                        "is_active": radar.is_active
                    }
                    for radar in berth.radars
                ]
            }

    # Ship not found
    raise HTTPException(
        status_code=404,
        detail=f"Ship with vessel ID {ship_id} not found in any berth"
    )


@app.get("/ships/{ship_id}/history")
async def get_ship_history(ship_id: str, limit: int = 100):
    """
    Get historical tension data for a specific ship.
    Useful for trend analysis and charts.
    """
    ship_history = []

    for entry in list(mooring_db)[-limit:]:
        # Search for ship in this historical entry
        for berth in entry.berths:
            ship = berth.ship
            if ship and ship.vesselId == ship_id:
                # Extract key metrics
                total_tension = 0
                tensions_by_line = {}

                for bollard in berth.bollards:
                    for hook in bollard.hooks:
                        if hook.tension:
                            total_tension += hook.tension
                            line_type = hook.attachedLine
                            if line_type:
                                if line_type not in tensions_by_line:
                                    tensions_by_line[line_type] = []
                                tensions_by_line[line_type].append(hook.tension)

                ship_history.append({
                    'timestamp': entry.timestamp,
                    'total_tension': total_tension,
                    'tensions_by_line': {
                        line: sum(tensions)
                        for line, tensions in tensions_by_line.items()
                    }
                })
                break

    if not ship_history:
        raise HTTPException(
            status_code=404,
            detail=f"No historical data found for ship {ship_id}"
        )

    return {
        "ship_id": ship_id,
        "data_points": len(ship_history),
        "history": ship_history
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

    # --- NEW: compute colours for all hooks in this berth ---
    hook_colours = compute_hook_colours_for_berth(berth)
    # --------------------------------------------------------

    # Build comprehensive tension data
    bollard_data = []
    for bollard in berth.bollards:
        hooks_data = []
        for hook in bollard.hooks:
            colour = hook_colours.get((berth.name, hook.name))
            hooks_data.append({
                "name": hook.name,
                "tension": hook.tension,
                "status": hook.tension_status,
                "faulted": hook.faulted,
                "line_type": hook.attachedLine,
                "is_active": hook.is_active,
                "colour": colour  # <--- NEW FIELD
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
    """Get data formatted for visualization."""
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    berth = current_data.get_berth_by_name(berth_name)
    if berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {berth_name} not found")

    viz_data = {
        "berth": berth_name,
        "ship": berth.ship.model_dump() if berth.ship else None,
        "bollards": []
    }

    for idx, bollard in enumerate(berth.bollards):
        bollard_viz = {
            "id": bollard.name,
            "index": idx,
            "position": idx / len(berth.bollards),
            "total_tension": bollard.total_tension,
            "lines": []
        }

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

    viz_data["summary"] = {
        "total_tension": berth.total_berth_tension,
        "line_type_totals": berth.get_all_tensions_by_line_type(),
        "bollard_count": len(berth.bollards),
        "active_bollard_count": len([b for b in berth.bollards if b.active_hook_count > 0])
    }

    return viz_data



if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)