"""Core data models for GhostRunner. Pydantic v2 at every boundary."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RunnerState = Literal["CRUISING", "ACCELERATING", "EXHAUSTED", "STOPPED"]


class Landmark(BaseModel):
    """A point of interest along the route."""
    id: str
    name: str
    kind: str
    lat: float
    lon: float
    chainage_m: float = 0.0
    side: Literal["left", "right", "ahead"] = "ahead"
    offset_m: float = 0.0
    source: Literal["osm", "demo"] = "osm"


class Maneuver(BaseModel):
    """A turn or direction change on the route."""
    chainage_m: float
    type: Literal[
        "left", "right", "slight_left", "slight_right",
        "sharp_left", "sharp_right", "uturn", "continue", "arrive"
    ]
    street: str | None = None
    instruction: str


class RouteModel(BaseModel):
    """Complete route with densified geometry, maneuvers and landmarks."""
    length_m: float
    points: list[tuple[float, float]]  # (lat, lon) densified ~5m spacing
    maneuvers: list[Maneuver]
    landmarks: list[Landmark]
    utm_epsg: int


class Beat(BaseModel):
    """A single narrative beat anchored to a route position."""
    id: str
    anchor_chainage_m: float
    expires_chainage_m: float
    kind: Literal[
        "INTRO", "NAV", "LANDMARK", "TENSION", "CHALLENGE",
        "RECOVERY", "CHECKPOINT", "FINALE"
    ]
    priority: int  # NAV=100 > CHECKPOINT=90 > LANDMARK=80 > CHALLENGE=70 > TENSION=60
    speaker: Literal["operator", "antagonist"] = "operator"
    variants: dict[str, str] = Field(default_factory=dict)
    audio: dict[str, str] = Field(default_factory=dict)
    duration_s: dict[str, float] = Field(default_factory=dict)
    sfx: str | None = None

    @staticmethod
    def priority_for(kind: str) -> int:
        """Return canonical priority for a beat kind."""
        return {
            "NAV": 100, "CHECKPOINT": 90, "LANDMARK": 80,
            "CHALLENGE": 70, "TENSION": 60, "RECOVERY": 50,
            "INTRO": 110, "FINALE": 110,
        }.get(kind, 50)


class TelemetryFix(BaseModel):
    """A single GPS fix from the runner or simulator."""
    t: float
    lat: float
    lon: float
    speed: float = 0.0
    heading: float = 0.0
    acc: float = 10.0
