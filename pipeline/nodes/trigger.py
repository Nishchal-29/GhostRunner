"""Trigger engine to determine the next narrative event."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from config import get_settings
from engine.models import Beat, RouteModel, Landmark, Maneuver

logger = logging.getLogger("ghostrunner.trigger")


class TriggerContext:
    """Inputs for the trigger node."""
    def __init__(
        self,
        route: RouteModel,
        current_chainage_m: float,
        speed_mps: float,
        played_events: list[dict],
        last_beat_chainage_m: float
    ):
        self.route = route
        self.current_chainage_m = current_chainage_m
        self.speed_mps = speed_mps
        self.played_events = played_events
        self.last_beat_chainage_m = last_beat_chainage_m
        self.settings = get_settings()

        self.played_ids = {e["beat_id"] for e in played_events}


def _find_next_maneuver(ctx: TriggerContext, lookahead_m: float = 80.0) -> Maneuver | None:
    """Find the next unplayed maneuver within lookahead distance."""
    for m in ctx.route.maneuvers:
        # Check if ahead and within window
        if ctx.current_chainage_m <= m.chainage_m <= ctx.current_chainage_m + lookahead_m:
            # Generate a stable ID for the maneuver
            m_id = f"nav_{m.chainage_m:.1f}_{m.type}"
            if m_id not in ctx.played_ids:
                return m
    return None


def _find_next_landmark(ctx: TriggerContext, lookahead_m: float = 60.0) -> Landmark | None:
    """Find the next unplayed landmark within lookahead distance."""
    for lm in ctx.route.landmarks:
        if ctx.current_chainage_m <= lm.chainage_m <= ctx.current_chainage_m + lookahead_m:
            lm_id = f"lm_{lm.id}"
            if lm_id not in ctx.played_ids:
                return lm
    return None


def determine_next_beat(ctx: TriggerContext) -> Beat | None:
    """Evaluate heuristics and return the next Beat if triggered, else None."""
    # 1. High priority: Navigation
    # Give nav 80m lookahead so there is time to narrate before the turn
    nav = _find_next_maneuver(ctx, lookahead_m=80.0)
    if nav and nav.type != "continue":
        # Don't trigger if it's too far and we are moving very slowly
        time_to_turn = (nav.chainage_m - ctx.current_chainage_m) / max(ctx.speed_mps, 1.0)
        if time_to_turn < 40.0:  # Trigger if within 40s
            beat_id = f"nav_{nav.chainage_m:.1f}_{nav.type}"
            return Beat(
                id=beat_id,
                anchor_chainage_m=nav.chainage_m,
                expires_chainage_m=nav.chainage_m + 50.0,
                kind="NAV",
                priority=Beat.priority_for("NAV"),
                variants={"operator": f"In {(nav.chainage_m - ctx.current_chainage_m):.0f} meters, {nav.instruction}"}
            )

    # 2. Medium priority: Landmarks
    lm = _find_next_landmark(ctx, lookahead_m=60.0)
    if lm:
        beat_id = f"lm_{lm.id}"
        return Beat(
            id=beat_id,
            anchor_chainage_m=lm.chainage_m,
            expires_chainage_m=lm.chainage_m + 80.0,
            kind="LANDMARK",
            priority=Beat.priority_for("LANDMARK"),
            variants={"operator": f"Approaching {lm.name} on your {lm.side}."}
        )

    # 3. Low priority: Tension/Pacing fill
    dist_since = ctx.current_chainage_m - ctx.last_beat_chainage_m
    if dist_since > ctx.settings.beat_spacing_m:
        beat_id = f"fill_{uuid.uuid4().hex[:8]}"
        return Beat(
            id=beat_id,
            anchor_chainage_m=ctx.current_chainage_m,
            expires_chainage_m=ctx.current_chainage_m + 200.0,
            kind="TENSION",
            priority=Beat.priority_for("TENSION"),
            variants={"operator": "Keep moving, no sign of them yet."}
        )

    return None
