"""FastAPI application: lifespan, routers, static files, health."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import get_settings
from engine.store import Store

logger = logging.getLogger("ghostrunner")


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return json.dumps(obj)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_health: dict[str, Any] = {}
def set_health(key: str, value: Any) -> None: _health[key] = value
def get_health() -> dict[str, Any]: return dict(_health)


@asynccontextmanager
async def lifespan(application: FastAPI):
    _setup_logging()
    store = Store()
    await store.connect()
    await store.ensure_tables()
    application.state.store = store
    set_health("postgres", "connected")
    yield
    await store.close()


app = FastAPI(title="GhostRunner", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.ws import router as ws_router
app.include_router(ws_router, prefix="/ws")

from api.missions import router as missions_router
app.include_router(missions_router, prefix="/api/missions")

@app.get("/health")
async def health():
    return get_health()

_project_root = Path(__file__).resolve().parent.parent
_client_dir = _project_root / "client"
if _client_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_client_dir), html=True), name="static")

_storage_audio = _project_root / "storage" / "audio"
_storage_audio.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(_storage_audio)), name="audio")


@app.get("/")
async def root():
    index_file = _client_dir / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "GhostRunner API", "docs": "/docs", "app": "/static/index.html"}
