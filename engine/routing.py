"""Valhalla routing client and loop generation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import polyline
from pydantic import BaseModel
from pyproj import Geod
from shapely.geometry import LineString
import numpy as np

from config import get_settings
from engine.models import Maneuver

logger = logging.getLogger("ghostrunner.routing")


class SnappedPoint(BaseModel):
    lat: float
    lon: float
    edge_index: int | None = None


class RawRoute(BaseModel):
    locations: list[dict]
    legs: list[dict]
    summary: dict


class ValhallaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=3.0))
        self.semaphore = asyncio.Semaphore(3)

    async def close(self) -> None:
        await self.client.aclose()

    async def _post(self, endpoint: str, json_data: dict) -> dict:
        url = f"{self.settings.valhalla_url}{endpoint}"
        retries = 3
        backoff = 1.0

        async with self.semaphore:
            for attempt in range(retries):
                try:
                    r = await self.client.post(url, json=json_data)
                    if r.status_code == 200:
                        return r.json()
                    elif r.status_code in (429, 500, 502, 503, 504):
                        logger.warning("Valhalla %d, retrying in %.1fs", r.status_code, backoff)
                    else:
                        r.raise_for_status()
                except httpx.RequestError as e:
                    logger.warning("Valhalla error: %s, retrying in %.1fs", e, backoff)

                if attempt < retries - 1:
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
            raise RuntimeError("Valhalla request failed after retries")

    async def route(self, locations: list[dict[str, Any]], costing_options: dict | None = None) -> RawRoute:
        if costing_options is None:
            costing_options = {
                "pedestrian": {
                    "use_hills": 0.3,
                    "use_lit": 0.5,
                    "use_alleys": 0.2,
                    "step_penalty": 20.0
                }
            }
        req = {
            "locations": locations,
            "costing": "pedestrian",
            "costing_options": costing_options,
            "directions_options": {"units": "kilometers", "language": "en-US"}
        }
        res = await self._post("/route", req)
        trip = res.get("trip", {})
        return RawRoute(
            locations=trip.get("locations", []),
            legs=trip.get("legs", []),
            summary=trip.get("summary", {})
        )

    async def locate(self, lat: float, lon: float) -> SnappedPoint:
        req = {
            "locations": [{"lat": lat, "lon": lon}],
            "costing": "pedestrian"
        }
        res = await self._post("/locate", req)
        results = res if isinstance(res, list) else res.get("results", [])
        if not results:
            raise ValueError(f"No nearby pedestrian edge for {lat}, {lon}")

        edges = results[0].get("edges")
        if not edges:
            raise ValueError(f"No nearby pedestrian edge for {lat}, {lon}")

        edge = edges[0]
        c = edge.get("correlated_lat", lat)
        c_lon = edge.get("correlated_lon", lon)
        return SnappedPoint(lat=c, lon=c_lon, edge_index=edge.get("edge_index"))


def decode_and_map_maneuvers(raw: RawRoute) -> tuple[list[tuple[float, float]], list[Maneuver]]:
    """Decode polyline and map maneuvers correctly across multiple legs."""
    all_points: list[tuple[float, float]] = []
    maneuvers: list[Maneuver] = []

    current_point_offset = 0

    # Maneuver type mapping
    # Valhalla types: https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/
    type_map = {
        1: "continue", 2: "continue", 3: "continue", 
        4: "continue", 5: "continue", 6: "continue",
        9: "slight_right", 10: "right", 11: "sharp_right",
        12: "uturn",
        13: "uturn",
        14: "sharp_left", 15: "left", 16: "slight_left",
        # Default fallback
    }

    for leg in raw.legs:
        shape = leg.get("shape", "")
        # Valhalla precision is 6
        points = polyline.decode(shape, 6)

        if all_points and points:
            # Drop the duplicate join point (start of this leg = end of last leg)
            points = points[1:]

        leg_start_index = current_point_offset

        for m in leg.get("maneuvers", []):
            m_type_code = m.get("type", 0)
            m_type = type_map.get(m_type_code, "continue")

            # Map index
            begin_idx = m.get("begin_shape_index", 0)
            # If we dropped the first point of the leg, we subtract 1, EXCEPT for the very first leg.
            if all_points and begin_idx > 0:
                global_idx = leg_start_index + begin_idx - 1
            elif all_points and begin_idx == 0:
                global_idx = leg_start_index - 1
            else:
                global_idx = leg_start_index + begin_idx

            streets = m.get("street_names", [])
            street = streets[0] if streets else None

            # Dummy chainage to be populated later by RouteModel
            man = Maneuver(
                chainage_m=float(global_idx),  # Storing index temporarily, replaced later
                type=m_type,
                street=street,
                instruction=m.get("instruction", "")
            )
            maneuvers.append(man)

        all_points.extend(points)
        current_point_offset = len(all_points)

    return all_points, maneuvers


async def generate_route(client: ValhallaClient, start: tuple[float, float], destination: tuple[float, float]) -> RawRoute:
    locs = [
        {"lat": start[0], "lon": start[1], "type": "break"},
        {"lat": destination[0], "lon": destination[1], "type": "break"}
    ]
    return await client.route(locs)


async def _generate_loop_candidate(client: ValhallaClient, start: tuple[float, float], waypoints: list[tuple[float, float]]) -> RawRoute | None:
    try:
        locs = [{"lat": start[0], "lon": start[1], "type": "break"}]
        for w in waypoints:
            snap = await client.locate(w[0], w[1])
            locs.append({"lat": snap.lat, "lon": snap.lon, "type": "break"})
        locs.append({"lat": start[0], "lon": start[1], "type": "break"})
        return await client.route(locs)
    except Exception as e:
        logger.warning("Loop candidate failed: %s", e)
        return None

def _get_overlap_ratio(points: list[tuple[float, float]], utm_epsg: int) -> float:
    # A bit complex to do cleanly, approximate by checking distances between segments
    # Will use shapely segmentization in route_model, simple bounding buffer here
    try:
        from engine.route_model import to_utm
        import pyproj
        from shapely.geometry import LineString

        transformer = pyproj.Transformer.from_crs(4326, utm_epsg, always_xy=True)
        utm_pts = [transformer.transform(lon, lat) for lat, lon in points]
        line = LineString(utm_pts)

        # Buffer the line by a small amount, then check self-intersections or overlaps?
        # A simpler way: discretize to 10m grid, count unique vs total cells
        if len(utm_pts) < 2:
            return 0.0

        L = line.length
        # Sample points every 10m
        num_samples = int(L / 10)
        if num_samples == 0: return 0.0

        samples = [line.interpolate(i * 10) for i in range(num_samples)]

        grid_size = 15.0
        cells = set()
        for p in samples:
            cells.add((int(p.x / grid_size), int(p.y / grid_size)))

        ratio = 1.0 - (len(cells) / num_samples)
        return max(0.0, ratio)
    except Exception:
        return 0.0

async def generate_loop(client: ValhallaClient, start: tuple[float, float], target_distance_m: float) -> RawRoute:
    """Generate a closed loop route of approximately target_distance_m."""
    from pyproj import Geod
    geod = Geod(ellps="WGS84")

    async def get_candidate(r: float) -> tuple[RawRoute, float, float]:
        # Generate 3 candidates at bearings
        bearings = [(60, 180, 300), (180, 300, 60), (300, 60, 180)]
        tasks = []
        for b1, b2, b3 in bearings:
            w1_lon, w1_lat, _ = geod.fwd(start[1], start[0], b1, r)
            w2_lon, w2_lat, _ = geod.fwd(w1_lon, w1_lat, b2, r)
            w3_lon, w3_lat, _ = geod.fwd(w2_lon, w2_lat, b3, r)
            tasks.append(_generate_loop_candidate(client, start, [(w1_lat, w1_lon), (w2_lat, w2_lon)]))

        results = await asyncio.gather(*tasks)

        best_route = None
        best_score = float('inf')
        best_overlap = 0.0

        zone = int((start[1] + 180) / 6) + 1
        utm_epsg = 32600 + zone if start[0] >= 0 else 32700 + zone

        for res in results:
            if not res: continue

            pts, _ = decode_and_map_maneuvers(res)
            overlap = _get_overlap_ratio(pts, utm_epsg)

            d_actual = res.summary.get("length", 0) * 1000.0

            # Score = difference + penalty for overlap
            score = abs(d_actual - target_distance_m) + (overlap * 2000.0) 

            if score < best_score:
                best_score = score
                best_route = res
                best_overlap = overlap

        return best_route, best_score, best_overlap

    r = target_distance_m / 4.0
    best, score, overlap = await get_candidate(r)

    if best is not None:
        d_actual = best.summary.get("length", 0) * 1000.0
        k = target_distance_m / max(d_actual, 1.0)

        # If off by > 15%, do one recalibration pass
        if abs(k - 1.0) > 0.15:
            r2 = r * k
            best2, score2, overlap2 = await get_candidate(r2)
            if best2 is not None and score2 < score:
                return best2

        return best

    raise ValueError("Failed to generate any loop candidates")
