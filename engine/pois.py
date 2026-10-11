"""Overpass client, H3 binning, and POI snapping."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import h3
import httpx
from pydantic import BaseModel

from config import get_settings
from engine.models import Landmark, RouteModel
from engine.store import Store

logger = logging.getLogger("ghostrunner.pois")


class OverpassClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.urls = self.settings.overpass_url_list
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=5.0),
            headers={"User-Agent": "GhostRunner/1.0 (contact: admin@ghostrunner.dev)"}
        )
        self.semaphore = asyncio.Semaphore(2)

    async def close(self) -> None:
        await self.client.aclose()

    async def _post(self, query: str) -> dict:
        backoff = 2.0
        max_retries = 3

        async with self.semaphore:
            for attempt in range(max_retries):
                for url in self.urls:
                    try:
                        r = await self.client.post(url, data={"data": query})
                        if r.status_code == 200:
                            return r.json()
                        elif r.status_code == 429:
                            logger.warning("Overpass 429 on %s, waiting %.1fs", url, backoff)
                        else:
                            logger.warning("Overpass %d on %s", r.status_code, url)
                    except httpx.RequestError as e:
                        logger.warning("Overpass error %s on %s", e, url)

                await asyncio.sleep(backoff)
                backoff *= 1.5

        raise RuntimeError("Overpass query failed after retries")

    async def fetch_bbox(self, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[dict]:
        """Fetch POIs for a bounding box covering the route."""
        pad = 0.002
        bbox = f"{min_lat - pad:.6f},{min_lon - pad:.6f},{max_lat + pad:.6f},{max_lon + pad:.6f}"
        q = f"""[out:json][timeout:15];
(
  nwr["name"]["amenity"]({bbox});
  nwr["name"]["historic"]({bbox});
  nwr["name"]["tourism"]({bbox});
  nwr["name"]["leisure"]({bbox});
  nwr["name"]["shop"]({bbox});
);
out center qt;"""
        res = await self._post(q)
        return res.get("elements", [])

    async def fetch_cells(self, cells: list[str]) -> list[dict]:
        return []


def map_poi_kind(tags: dict) -> str:
    """Map OSM tags to a simplified kind."""
    if "historic" in tags:
        return "historic"
    if "tourism" in tags:
        return tags["tourism"]
    if "natural" in tags:
        return tags["natural"]
    if "amenity" in tags:
        return tags["amenity"]
    if "leisure" in tags:
        return tags["leisure"]
    if "shop" in tags:
        return "shop"
    if "building" in tags:
        return "building"
    return "poi"


def extract_poi_name(tags: dict) -> str | None:
    return tags.get("name:en") or tags.get("name")


def get_route_cells(points: list[tuple[float, float]], resolution: int = 9) -> list[str]:
    cells = set()
    for lat, lon in points:
        cells.add(h3.latlng_to_cell(lat, lon, resolution))
    expanded = set()
    for cell in cells:
        expanded.update(h3.grid_disk(cell, 1))
    return list(expanded)


async def enrich_route_with_pois(store: Store, overpass: OverpassClient, route_model: RouteModel) -> None:
    """Fetch POIs, save to DB, snap to route, and populate route_model.landmarks."""
    if not route_model.points:
        return

    lats = [p[0] for p in route_model.points]
    lons = [p[1] for p in route_model.points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    cells = get_route_cells(route_model.points, resolution=9)
    fetched_cells = await store.get_fetched_cells()
    missing_cells = [c for c in cells if c not in fetched_cells]

    if missing_cells:
        logger.info("Fetching POIs via bounding box for route")
        try:
            elements = await overpass.fetch_bbox(min_lat, min_lon, max_lat, max_lon)
            pois_to_save = []
            for el in elements:
                tags = el.get("tags", {})
                name = extract_poi_name(tags)
                if not name:
                    continue
                kind = map_poi_kind(tags)
                lat = el.get("lat") or el.get("center", {}).get("lat")
                lon = el.get("lon") or el.get("center", {}).get("lon")
                if lat is None or lon is None:
                    continue
                cell = h3.latlng_to_cell(lat, lon, 9)
                pois_to_save.append({
                    "osm_type": el["type"],
                    "osm_id": el["id"],
                    "h3_r9": cell,
                    "name": name,
                    "kind": kind,
                    "lat": lat,
                    "lon": lon,
                    "tags": tags
                })
            if pois_to_save:
                await store.save_pois(pois_to_save)
            await store.mark_cells_fetched(missing_cells)
        except Exception as e:
            logger.warning("Overpass fetch failed, will fallback to cached/derived landmarks: %s", e)

    db_pois = await store.get_pois_in_cells(cells)
    from engine.route_model import RouteGeometry
    geom = RouteGeometry(route_model.points)

    landmarks = []
    for row in db_pois:
        c_m, offset_m = geom.chainage_windowed(row["lat"], row["lon"], hint_m=0, back_m=10000, ahead_m=10000)
        if offset_m > 45.0:
            continue
        side, real_offset = geom.get_side(row["lat"], row["lon"], c_m)
        lm = Landmark(
            id=f"{row['osm_type']}_{row['osm_id']}",
            name=row["name"],
            kind=row["kind"],
            lat=row["lat"],
            lon=row["lon"],
            chainage_m=c_m,
            side=side,
            offset_m=real_offset,
            source="osm"
        )
        landmarks.append(lm)

    # If Overpass yielded few landmarks along this corridor, derive waypoint landmarks from maneuvers
    if len(landmarks) < 3 and route_model.maneuvers:
        for m in route_model.maneuvers:
            if m.street_name and len(m.street_name.strip()) > 1:
                lat, lon = geom.point_at(m.chainage_m)
                side, real_offset = geom.get_side(lat, lon, m.chainage_m)
                landmarks.append(Landmark(
                    id=f"street_{int(m.chainage_m)}",
                    name=f"{m.street_name} Junction",
                    kind="junction",
                    lat=lat,
                    lon=lon,
                    chainage_m=m.chainage_m,
                    side=side,
                    offset_m=5.0,
                    source="route"
                ))

    landmarks.sort(key=lambda x: x.chainage_m)
    route_model.landmarks = landmarks
