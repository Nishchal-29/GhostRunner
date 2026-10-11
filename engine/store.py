"""Postgres storage layer using psycopg3 AsyncConnectionPool."""
from __future__ import annotations

import json
import logging
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from config import get_settings

logger = logging.getLogger("ghostrunner.store")

_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    genre TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS routes (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    route JSONB NOT NULL,
    utm_epsg INT NOT NULL,
    length_m REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS beats (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    beat_id TEXT NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY (session_id, beat_id)
);

CREATE TABLE IF NOT EXISTS played_events (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    beat_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    chainage_m REAL NOT NULL,
    played_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS http_cache (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pois (
    osm_type TEXT NOT NULL,
    osm_id BIGINT NOT NULL,
    h3_r9 TEXT,
    name TEXT,
    kind TEXT,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    tags JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (osm_type, osm_id)
);

CREATE TABLE IF NOT EXISTS poi_cells (
    h3_r9 TEXT PRIMARY KEY,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    genre TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}',
    route JSONB,
    beats JSONB,
    stats JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class Store:
    """Async Postgres store backed by psycopg3 connection pool."""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        settings = get_settings()
        self._pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=2,
            max_size=10,
            open=False,
        )
        await self._pool.open()
        logger.info("Connection pool opened")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("Connection pool closed")

    async def ensure_tables(self) -> None:
        async with self.conn() as c:
            await c.execute(_TABLES)
        logger.info("Tables ensured")

    def conn(self):
        """Return an async context manager for a pooled connection."""
        assert self._pool is not None, "Store not connected"
        return self._pool.connection()

    # ── Session CRUD ───────────────────────────────────────────────
    async def create_session(self, session_id: str, genre: str, params: dict) -> None:
        async with self.conn() as c:
            await c.execute(
                "INSERT INTO sessions (id, genre, params) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET params=%s, updated_at=now()",
                (session_id, genre, json.dumps(params), json.dumps(params)),
            )

    async def update_session_status(self, session_id: str, status: str) -> None:
        async with self.conn() as c:
            await c.execute(
                "UPDATE sessions SET status=%s, updated_at=now() WHERE id=%s",
                (status, session_id),
            )

    async def get_session(self, session_id: str) -> dict | None:
        async with self.conn() as c:
            c.row_factory = dict_row
            row = await c.execute(
                "SELECT * FROM sessions WHERE id=%s", (session_id,)
            )
            return await row.fetchone()

    # ── Route ──────────────────────────────────────────────────────
    async def save_route(self, session_id: str, route: dict, utm_epsg: int, length_m: float) -> None:
        async with self.conn() as c:
            await c.execute(
                "INSERT INTO routes (session_id, route, utm_epsg, length_m) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (session_id) DO UPDATE SET route=%s, utm_epsg=%s, length_m=%s",
                (session_id, json.dumps(route), utm_epsg, length_m,
                 json.dumps(route), utm_epsg, length_m),
            )

    # ── Beats ──────────────────────────────────────────────────────
    async def save_beat(self, session_id: str, beat_id: str, data: dict) -> None:
        async with self.conn() as c:
            await c.execute(
                "INSERT INTO beats (session_id, beat_id, data) VALUES (%s, %s, %s) "
                "ON CONFLICT (session_id, beat_id) DO UPDATE SET data=%s",
                (session_id, beat_id, json.dumps(data), json.dumps(data)),
            )

    async def get_beats(self, session_id: str) -> list[dict]:
        async with self.conn() as c:
            c.row_factory = dict_row
            rows = await c.execute(
                "SELECT * FROM beats WHERE session_id=%s ORDER BY beat_id", (session_id,)
            )
            return [r["data"] for r in await rows.fetchall()]

    # ── Played events ─────────────────────────────────────────────
    async def record_played(self, session_id: str, beat_id: str, variant: str, chainage_m: float) -> None:
        async with self.conn() as c:
            await c.execute(
                "INSERT INTO played_events (session_id, beat_id, variant, chainage_m) VALUES (%s, %s, %s, %s)",
                (session_id, beat_id, variant, chainage_m),
            )

    async def get_played(self, session_id: str) -> list[dict]:
        async with self.conn() as c:
            c.row_factory = dict_row
            rows = await c.execute(
                "SELECT * FROM played_events WHERE session_id=%s ORDER BY played_at",
                (session_id,),
            )
            return await rows.fetchall()

    # ── HTTP cache ─────────────────────────────────────────────────
    async def cache_get(self, key: str) -> dict | None:
        async with self.conn() as c:
            c.row_factory = dict_row
            row = await c.execute("SELECT value FROM http_cache WHERE key=%s", (key,))
            r = await row.fetchone()
            return r["value"] if r else None

    async def cache_set(self, key: str, value: dict) -> None:
        async with self.conn() as c:
            await c.execute(
                "INSERT INTO http_cache (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value=%s, created_at=now()",
                (key, json.dumps(value), json.dumps(value)),
            )

    # ── POIs ───────────────────────────────────────────────────────
    async def save_pois(self, pois: list[dict]) -> None:
        if not pois:
            return
        async with self.conn() as c:
            for poi in pois:
                await c.execute(
                    """INSERT INTO pois (osm_type, osm_id, h3_r9, name, kind, lat, lon, tags)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (osm_type, osm_id) DO UPDATE SET
                        h3_r9=%s, name=%s, kind=%s, lat=%s, lon=%s, tags=%s, fetched_at=now()""",
                    (poi["osm_type"], poi["osm_id"], poi.get("h3_r9"), poi.get("name"),
                     poi.get("kind"), poi["lat"], poi["lon"], json.dumps(poi.get("tags", {})),
                     poi.get("h3_r9"), poi.get("name"), poi.get("kind"),
                     poi["lat"], poi["lon"], json.dumps(poi.get("tags", {}))),
                )

    async def mark_cells_fetched(self, cells: list[str]) -> None:
        async with self.conn() as c:
            for cell in cells:
                await c.execute(
                    "INSERT INTO poi_cells (h3_r9) VALUES (%s) ON CONFLICT DO NOTHING",
                    (cell,),
                )

    async def get_fetched_cells(self) -> set[str]:
        async with self.conn() as c:
            rows = await c.execute("SELECT h3_r9 FROM poi_cells")
            return {r[0] for r in await rows.fetchall()}

    async def get_pois_in_cells(self, cells: list[str]) -> list[dict]:
        if not cells:
            return []
        async with self.conn() as c:
            c.row_factory = dict_row
            placeholders = ",".join(["%s"] * len(cells))
            rows = await c.execute(
                f"SELECT * FROM pois WHERE h3_r9 IN ({placeholders})", cells
            )
            return await rows.fetchall()

    # ── Missions ──────────────────────────────────────────────────
    async def save_mission(self, mission_id: str, genre: str, params: dict,
                           route: dict, beats: list, stats: dict) -> None:
        async with self.conn() as c:
            await c.execute(
                """INSERT INTO missions (id, genre, params, route, beats, stats)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET route=%s, beats=%s, stats=%s""",
                (mission_id, genre, json.dumps(params), json.dumps(route),
                 json.dumps(beats), json.dumps(stats),
                 json.dumps(route), json.dumps(beats), json.dumps(stats)),
            )

    async def get_missions(self) -> list[dict]:
        async with self.conn() as c:
            c.row_factory = dict_row
            rows = await c.execute(
                "SELECT id, genre, params, stats, created_at FROM missions ORDER BY created_at DESC"
            )
            return await rows.fetchall()

    async def get_mission(self, mission_id: str) -> dict | None:
        async with self.conn() as c:
            c.row_factory = dict_row
            row = await c.execute("SELECT * FROM missions WHERE id=%s", (mission_id,))
            return await row.fetchone()

    async def delete_mission(self, mission_id: str) -> bool:
        async with self.conn() as c:
            result = await c.execute("DELETE FROM missions WHERE id=%s", (mission_id,))
            return result.rowcount > 0
