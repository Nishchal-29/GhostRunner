from __future__ import annotations

async def _get_store(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if not store:
        store = Store()
        await store.connect()
        await store.ensure_tables()
        request.app.state.store = store
    return store
"""Mission creation, retrieval, and presets router."""

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import get_settings
from engine.store import Store
from pipeline.compile import run_compiler

logger = logging.getLogger("ghostrunner.missions")
router = APIRouter()


class CreateMissionRequest(BaseModel):
    start_lat: Optional[float] = Field(None, description="Starting latitude (GPS or selected on map)")
    start_lon: Optional[float] = Field(None, description="Starting longitude")
    distance_m: float = Field(2500.0, ge=500.0, le=15000.0, description="Target distance in meters")
    genre: str = Field("cyberpunk", description="Story genre: cyberpunk, zombie, spy")


PRESETS = [
    {
        "id": "times-square",
        "name": "Times Square Cyber Corridor",
        "genre": "cyberpunk",
        "distance_m": 1800,
        "lat": 40.7580,
        "lon": -73.9855,
        "location_name": "Times Square, New York",
        "tagline": "Neon canyons & CorpSec surveillance sweeps",
        "description": "High-density pedestrian corridor through Midtown Manhattan. Evade automated corporate security grids while transporting an encrypted neural package."
    },
    {
        "id": "central-park",
        "name": "Central Park Outbreak",
        "genre": "zombie",
        "distance_m": 3000,
        "lat": 40.7660,
        "lon": -73.9770,
        "location_name": "Central Park South, New York",
        "tagline": "Perimeter breach & survivor extraction",
        "description": "The infected have breached 59th street. Follow your tactical dispatcher through park pathways and perimeter stone walls to reach the designated evacuation safehouse."
    },
    {
        "id": "empire-state",
        "name": "Midtown Exfiltration",
        "genre": "spy",
        "distance_m": 2200,
        "lat": 40.7484,
        "lon": -73.9857,
        "location_name": "Empire State Sector, New York",
        "tagline": "Cover blown & covert dead-drop relays",
        "description": "Hostile counter-intelligence has marked your profile. Your handler guides your evasive route between historic avenue landmarks to establish encrypted rendezvous."
    },
    {
        "id": "bryant-park",
        "name": "Bryant Park Neural Drop",
        "genre": "cyberpunk",
        "distance_m": 2000,
        "lat": 40.7536,
        "lon": -73.9832,
        "location_name": "Bryant Park / Public Library, New York",
        "tagline": "Underground syndicate data relay",
        "description": "Deliver classified corporate telemetry chips before the megacorp initiates a regional communication blackout."
    }
]


@router.get("/presets")
async def get_presets():
    """Return curated NYC demo mission presets."""
    return PRESETS


@router.get("/recent")
async def get_recent_missions(request: Request):
    """Return recently generated missions."""
    store = await _get_store(request)
    missions = await store.get_missions()
    return missions[:10]


@router.get("/{session_id}")
async def get_mission_by_id(session_id: str, request: Request):
    """Return details for a specific mission session."""
    store = await _get_store(request)
    mission = await store.get_mission(session_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/create")
async def create_mission(req: CreateMissionRequest, request: Request):
    """
    Generate a pedestrian loop route, enrich with OSM landmarks,
    generate narrative intro beat, and prepare session.
    Automatically handles coordinates outside the local tile bounds with NYC demo fallback.
    """
    store = await _get_store(request)
    settings = get_settings()

    session_id = f"mission_{uuid.uuid4().hex[:8]}"
    genre = req.genre.lower()
    if genre not in ("cyberpunk", "zombie", "spy"):
        genre = "cyberpunk"

    lat = req.start_lat if req.start_lat is not None else settings.demo_start_lat
    lon = req.start_lon if req.start_lon is not None else settings.demo_start_lon
    distance_m = float(req.distance_m)

    fallback_used = False
    fallback_reason = None

    # Check approximate bounding box for New York State / NYC (Valhalla tile extract)
    # NY bounding box is approx lat: 40.4 to 45.1, lon: -79.8 to -71.8
    is_in_ny = (40.4 <= lat <= 45.2) and (-80.0 <= lon <= -71.5)
    if not is_in_ny:
        fallback_used = True
        fallback_reason = "Your GPS location is outside the local New York offline map tiles. Automatically mapped to New York Midtown hub for demo simulation."
        lat = settings.demo_start_lat
        lon = settings.demo_start_lon

    params = {
        "start_lat": lat,
        "start_lon": lon,
        "distance_m": distance_m
    }

    await store.create_session(session_id, genre, params)

    try:
        await run_compiler(session_id, genre, params, store)
        session = await store.get_session(session_id)
        if session and "error" in session.get("status", ""):
            raise RuntimeError(session["status"])
    except Exception as exc:
        logger.warning("Primary compilation attempt failed (%s), falling back to Times Square", exc)
        fallback_used = True
        fallback_reason = f"Routing at requested point failed. Switched to Times Square demo hub."
        lat = settings.demo_start_lat
        lon = settings.demo_start_lon
        params["start_lat"] = lat
        params["start_lon"] = lon
        await run_compiler(session_id, genre, params, store)

    mission = await store.get_mission(session_id)
    if not mission:
        raise HTTPException(status_code=500, detail="Failed to compile mission route")

    intro_beat = mission["beats"][0] if mission.get("beats") else None

    return {
        "session_id": session_id,
        "genre": genre,
        "status": "ready",
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "start_coords": {"lat": lat, "lon": lon},
        "distance_m": distance_m,
        "route": mission["route"],
        "stats": mission.get("stats", {}),
        "intro_beat": intro_beat
    }
