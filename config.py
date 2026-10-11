"""Application configuration loaded from .env via pydantic-settings."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """GhostRunner configuration. All values come from environment or .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = ""
    ollama_url: str = "http://localhost:11434"

    # Routing
    valhalla_url: str = "http://localhost:8002"

    # Database
    database_url: str = "postgresql://devcontainers@/ghostrunner?host=/var/run/postgresql"

    # Overpass
    overpass_urls: str = ""

    # TTS
    tts_provider: str = "mock"
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_flash_v2_5"

    # Pacing
    pacing_backend: str = "rules"

    # Observability
    sentry_dsn: str = ""

    # Demo
    demo_start_lat: float = 40.7580
    demo_start_lon: float = -73.9855
    demo_sim_speed_mult: float = 2.0

    # Beats
    min_beat_gap_s: float = 20.0
    beat_spacing_m: float = 120.0

    # Storage
    storage_dir: Path = Path("./storage")

    @field_validator("overpass_urls", mode="before")
    @classmethod
    def _parse_overpass(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @property
    def overpass_url_list(self) -> list[str]:
        """Return Overpass URLs as a list, with public default fallback."""
        if self.overpass_urls:
            return [u.strip() for u in self.overpass_urls.split(",") if u.strip()]
        return ["https://overpass-api.de/api/interpreter"]

    @property
    def audio_dir(self) -> Path:
        d = self.storage_dir / "audio"
        d.mkdir(parents=True, exist_ok=True)
        return d


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton settings accessor."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
