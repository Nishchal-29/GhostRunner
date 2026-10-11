"""LangGraph compiler to set up a new mission."""
from __future__ import annotations

import logging
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END
import asyncio

from config import get_settings
from engine.store import Store
from engine.models import RouteModel, Beat
from engine.routing import ValhallaClient, generate_loop, decode_and_map_maneuvers
from engine.route_model import build_route_model
from engine.pois import OverpassClient, enrich_route_with_pois
from llm.writer import WriterNode
from audio.tts import generate_beat_audio

logger = logging.getLogger("ghostrunner.compile")


class CompileState(TypedDict):
    session_id: str
    genre: str
    params: dict[str, Any]
    route_raw: dict | None
    route: RouteModel | None
    intro_beat: Beat | None
    error: str | None


async def _generate_route_node(state: CompileState) -> CompileState:
    logger.info("Compiler [%s]: Generating route", state["session_id"])
    client = ValhallaClient()
    try:
        start_lat = state["params"].get("start_lat", get_settings().demo_start_lat)
        start_lon = state["params"].get("start_lon", get_settings().demo_start_lon)
        distance = state["params"].get("distance_m", 3000.0)

        raw = await generate_loop(client, (start_lat, start_lon), distance)
        state["route_raw"] = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)

        pts, maneuvers = decode_and_map_maneuvers(raw)
        route_model = build_route_model(pts, maneuvers)
        state["route"] = route_model

    except Exception as e:
        logger.error("Route generation failed: %s", e)
        state["error"] = str(e)
    finally:
        await client.close()

    return state


async def _enrich_pois_node(state: CompileState) -> CompileState:
    if state.get("error") or not state.get("route"):
        return state

    logger.info("Compiler [%s]: Enriching POIs", state["session_id"])
    store = Store()
    overpass = OverpassClient()

    try:
        await store.connect()
        # In a real app we might wrap enrich_route_with_pois to fail gracefully
        await enrich_route_with_pois(store, overpass, state["route"])
    except Exception as e:
        # We can still run without POIs, just log warning
        logger.warning("POI enrichment failed, continuing without landmarks: %s", e)
    finally:
        await overpass.close()
        await store.close()

    return state


async def _generate_intro_node(state: CompileState) -> CompileState:
    if state.get("error") or not state.get("route"):
        return state

    logger.info("Compiler [%s]: Generating Intro", state["session_id"])

    # Create draft beat
    beat = Beat(
        id=f"intro_{state['session_id']}",
        anchor_chainage_m=0.0,
        expires_chainage_m=50.0,
        kind="INTRO",
        priority=Beat.priority_for("INTRO"),
        variants={"operator": "Mission start. Follow the route."}
    )

    writer = WriterNode()
    try:
        # Write dialogue
        beat = await writer.write_beat(beat, state["genre"], 0.0)

        # Generate audio
        beat = await generate_beat_audio(beat)
        state["intro_beat"] = beat

    except Exception as e:
        logger.warning("Intro generation failed: %s", e)
    finally:
        await writer.close()

    return state


def build_compile_graph() -> StateGraph:
    """Build the linear compilation graph."""
    builder = StateGraph(CompileState)

    builder.add_node("generate_route", _generate_route_node)
    builder.add_node("enrich_pois", _enrich_pois_node)
    builder.add_node("generate_intro", _generate_intro_node)

    builder.set_entry_point("generate_route")

    builder.add_edge("generate_route", "enrich_pois")
    builder.add_edge("enrich_pois", "generate_intro")
    builder.add_edge("generate_intro", END)

    return builder.compile()


async def run_compiler(session_id: str, genre: str, params: dict, store: Store) -> None:
    """Runs the compilation graph and saves results to DB."""

    await store.update_session_status(session_id, "compiling")

    graph = build_compile_graph()
    initial_state = CompileState(
        session_id=session_id,
        genre=genre,
        params=params,
        route_raw=None,
        route=None,
        intro_beat=None,
        error=None
    )

    # Graph execution
    final_state = await graph.ainvoke(initial_state)

    if final_state.get("error"):
        await store.update_session_status(session_id, f"error: {final_state['error']}")
        return

    route = final_state["route"]
    intro = final_state["intro_beat"]

    # Save Route
    route_dict = route.model_dump()
    await store.save_route(session_id, route_dict, route.utm_epsg, route.length_m)

    # Save Mission state (simplified denormalized document for easy retrieval)
    beats = [intro.model_dump()] if intro else []
    stats = {"length_m": route.length_m, "maneuvers": len(route.maneuvers), "landmarks": len(route.landmarks)}

    await store.save_mission(
        mission_id=session_id,
        genre=genre,
        params=params,
        route=route_dict,
        beats=beats,
        stats=stats
    )

    if intro:
        await store.save_beat(session_id, intro.id, intro.model_dump())

    await store.update_session_status(session_id, "ready")
    logger.info("Mission %s compiled successfully", session_id)
