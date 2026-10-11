"""WebSocket endpoints, connection manager, and live telemetry streaming."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from engine.models import TelemetryFix, RouteModel
from engine.store import Store
from engine.simulator import Simulator
from pipeline.run import runtime_graph, RunState

logger = logging.getLogger("ghostrunner.ws")
router = APIRouter()


class SessionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}
        self.simulators: dict[str, Simulator] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.connections:
            self.connections[session_id] = []
        self.connections[session_id].append(websocket)
        logger.info("WS connected: %s", session_id)

    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.connections:
            if websocket in self.connections[session_id]:
                self.connections[session_id].remove(websocket)
            if not self.connections[session_id]:
                del self.connections[session_id]
                self._stop_sim(session_id)
        logger.info("WS disconnected: %s", session_id)

    async def broadcast(self, session_id: str, message: dict[str, Any]):
        if session_id in self.connections:
            for ws in list(self.connections[session_id]):
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    def _stop_sim(self, session_id: str):
        if session_id in self.simulators:
            self.simulators[session_id].stop()
            del self.simulators[session_id]
            logger.info("Simulator stopped for %s", session_id)


manager = SessionManager()


async def process_telemetry_loop(session_id: str, genre: str, route: RouteModel, store: Store, queue: asyncio.Queue):
    """Consumes telemetry from the queue, updates state, runs graph, and broadcasts."""
    current_chainage_m = 0.0
    last_beat_chainage_m = 0.0

    while True:
        try:
            fix: TelemetryFix = await queue.get()

            # Determine chainage from lat/lon via windowed snapping
            from engine.route_model import RouteGeometry
            geom = RouteGeometry(route.points)
            c_m, offset = geom.chainage_windowed(fix.lat, fix.lon, current_chainage_m, ahead_m=60, back_m=15)

            current_chainage_m = max(current_chainage_m, c_m)
            progress = min(1.0, current_chainage_m / max(1.0, route.length_m))

            # Broadcast rich telemetry fix
            await manager.broadcast(session_id, {
                "type": "telemetry",
                "lat": fix.lat,
                "lon": fix.lon,
                "speed": fix.speed,
                "chainage_m": current_chainage_m,
                "total_m": route.length_m,
                "progress": progress
            })

            # Load played events
            played = await store.get_played(session_id)

            state = RunState(
                session_id=session_id,
                genre=genre,
                telemetry=fix,
                route=route,
                current_chainage_m=current_chainage_m,
                speed_mps=fix.speed,
                played_events=played,
                last_beat_chainage_m=last_beat_chainage_m,
                draft_beat=None,
                ready_beat=None,
                error=None
            )

            final_state = await runtime_graph.ainvoke(state)

            if final_state.get("ready_beat"):
                beat = final_state["ready_beat"]
                logger.info("Triggered audio beat: %s (%s)", beat.id, beat.kind)
                await store.save_beat(session_id, beat.id, beat.model_dump())
                await store.record_played(session_id, beat.id, "operator", current_chainage_m)
                last_beat_chainage_m = current_chainage_m

                await manager.broadcast(session_id, {
                    "type": "beat",
                    "beat": beat.model_dump()
                })

            queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in process_telemetry_loop: %s", e)
            await asyncio.sleep(0.5)


@router.websocket("/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    store: Store = getattr(websocket.app.state, "store", None)
    if not store:
        store = Store()
        await store.connect()
        await store.ensure_tables()
        websocket.app.state.store = store

    # Load session and mission
    mission = await store.get_mission(session_id)
    if not mission:
        await websocket.accept()
        await websocket.send_json({"error": "Mission not found", "session_id": session_id})
        await websocket.close()
        return

    await manager.connect(session_id, websocket)

    route_model = RouteModel(**mission["route"])
    genre = mission["genre"]

    # Send initial session data so client can sync map and UI immediately
    await websocket.send_json({
        "type": "init",
        "session_id": session_id,
        "genre": genre,
        "route": mission["route"],
        "stats": mission.get("stats", {}),
        "intro_beat": mission["beats"][0] if mission.get("beats") else None
    })

    # Setup queue and process loop
    queue = asyncio.Queue()
    process_task = asyncio.create_task(process_telemetry_loop(session_id, genre, route_model, store, queue))

    # Setup simulator
    sim = Simulator(route_model, queue, base_speed_mps=3.2)
    manager.simulators[session_id] = sim
    sim.start()

    try:
        while True:
            data = await websocket.receive_json()
            cmd = data.get("cmd")
            if cmd == "pause":
                sim.stop()
                await websocket.send_json({"type": "status", "status": "paused"})
            elif cmd == "resume":
                sim.start()
                await websocket.send_json({"type": "status", "status": "running"})
            elif cmd == "speed":
                mult = float(data.get("mult", 1.0))
                sim.set_speed_mult(mult)
                await websocket.send_json({"type": "speed_changed", "mult": mult})
            elif cmd == "telemetry":
                # Real GPS fix sent by mobile client
                fix_data = data.get("fix", {})
                fix = TelemetryFix(
                    t=time.time(),
                    lat=fix_data.get("lat", 0.0),
                    lon=fix_data.get("lon", 0.0),
                    speed=fix_data.get("speed", 3.0),
                    heading=fix_data.get("heading", 0.0),
                    acc=fix_data.get("acc", 5.0)
                )
                await queue.put(fix)
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
        process_task.cancel()
    except Exception as e:
        logger.warning("WebSocket exception for %s: %s", session_id, e)
        manager.disconnect(session_id, websocket)
        process_task.cancel()
