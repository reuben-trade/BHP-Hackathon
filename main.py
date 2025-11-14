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

from models import MooringTerminal, WebhookRequest
from utils import calculate_orientation_from_two_radars, compute_hook_colours_for_berth
from websocket_client import ConnectionManager

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

manager = ConnectionManager(current_data)
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

    manager.current_data = data
    current_data = data
    mooring_db.append(data)

    await manager.broadcast(data.model_dump(mode='json'))

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
            hook_colours = compute_hook_colours_for_berth(berth)

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
                            "colour": colour,      # â† ADDED
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
                    "orientation_angle": math.degrees(orientation_angle),
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

@app.post("/webhook")
async def webhook(payload: WebhookRequest):
    """Receive webhook, update bollard colour upon request & process alert"""
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    current_berth = current_data.get_berth_by_name(payload.berth_name)
    if current_berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {payload.berth_name} not found")

    target_bollard = current_berth.get_bollard_by_name(payload.bollard_name)
    if target_bollard is None:
        raise HTTPException(status_code=404, detail=f"Bollard {payload.bollard_name} not found")

    # Update bollard colour if provided
    if payload.colour:
        target_bollard.colour = payload.colour

    # Update alert status
    target_bollard.alert = payload.alert

    return {
        "status": "success",
        "berth": payload.berth_name,
        "bollard": payload.bollard_name,
        "colour": target_bollard.colour,
        "alert": target_bollard.alert
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

    # hook_colours = compute_hook_colours_for_berth(berth)

    # Build comprehensive tension data
    bollard_data = []
    for bollard in berth.bollards:
        hooks_data = []
        for hook in bollard.hooks:
            # colour = hook_colours.get((berth.name, hook.name))
            hooks_data.append({
                "name": hook.name,
                "tension": hook.tension,
                "status": hook.tension_status,
                "faulted": hook.faulted,
                "line_type": hook.attachedLine,
                "is_active": hook.is_active,
                # "colour": colour
            })

        bollard_data.append({
            "name": bollard.name,
            "total_tension": bollard.total_tension,
            "active_hooks": bollard.active_hook_count,
            "total_hooks": bollard.hook_count,
            "tensions_by_line": bollard.get_tensions_by_line(),
            "hooks": hooks_data,
            "colour": bollard.colour
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


@app.get("/berth/{berth_name}/bollards/{bollard_name}")
async def get_bollard_details(berth_name: str, bollard_name: str):
    """Get detailed information for a specific bollard. This route is used for the tablet view."""
    if current_data is None:
        raise HTTPException(status_code=404, detail="No data available")

    berth = current_data.get_berth_by_name(berth_name)
    if berth is None:
        raise HTTPException(status_code=404, detail=f"Berth {berth_name} not found")

    bollard = berth.get_bollard_by_name(bollard_name)
    if bollard is None:
        raise HTTPException(status_code=404, detail=f"Bollard {bollard_name} not found")
    hook_colours = compute_hook_colours_for_berth(berth)

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
                "faulted": hook.faulted,
                "colour": hook_colours.get((berth.name, hook.name))
            }
            for hook in bollard.hooks
        ]
    }



if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)