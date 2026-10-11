"""Runtime LangGraph for active sessions."""
from __future__ import annotations

import logging
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END

from config import get_settings
from engine.store import Store
from engine.models import RouteModel, Beat, TelemetryFix
from pipeline.nodes.trigger import TriggerContext, determine_next_beat
from llm.writer import WriterNode
from audio.tts import generate_beat_audio

logger = logging.getLogger("ghostrunner.runtime")


class RunState(TypedDict):
    session_id: str
    genre: str
    telemetry: TelemetryFix
    route: RouteModel

    current_chainage_m: float
    speed_mps: float
    played_events: list[dict]
    last_beat_chainage_m: float

    draft_beat: Beat | None
    ready_beat: Beat | None

    error: str | None


async def _trigger_node(state: RunState) -> RunState:
    ctx = TriggerContext(
        route=state["route"],
        current_chainage_m=state["current_chainage_m"],
        speed_mps=state["speed_mps"],
        played_events=state["played_events"],
        last_beat_chainage_m=state["last_beat_chainage_m"]
    )

    draft = determine_next_beat(ctx)
    if draft:
        logger.info("Triggered new beat: %s", draft.id)
        state["draft_beat"] = draft

    return state


def _should_write(state: RunState) -> str:
    if state.get("draft_beat"):
        return "write"
    return "end"


async def _writer_node(state: RunState) -> RunState:
    if not state.get("draft_beat"):
        return state

    writer = WriterNode()
    try:
        beat = await writer.write_beat(state["draft_beat"], state["genre"], state["current_chainage_m"])
        state["draft_beat"] = beat
    except Exception as e:
        logger.warning("Writer error: %s", e)
    finally:
        await writer.close()

    return state


async def _tts_node(state: RunState) -> RunState:
    if not state.get("draft_beat"):
        return state

    try:
        beat = await generate_beat_audio(state["draft_beat"])
        state["ready_beat"] = beat
        state["draft_beat"] = None
    except Exception as e:
        logger.error("TTS error: %s", e)
        state["error"] = str(e)

    return state


def build_run_graph() -> StateGraph:
    builder = StateGraph(RunState)

    builder.add_node("trigger", _trigger_node)
    builder.add_node("writer", _writer_node)
    builder.add_node("tts", _tts_node)

    builder.set_entry_point("trigger")

    builder.add_conditional_edges("trigger", _should_write, {"write": "writer", "end": END})
    builder.add_edge("writer", "tts")
    builder.add_edge("tts", END)

    return builder.compile()

# Global compiled graph
runtime_graph = build_run_graph()
