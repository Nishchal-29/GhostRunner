"""LLM-based writer node to flesh out narrative beats."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import yaml

from config import get_settings
from engine.models import Beat

logger = logging.getLogger("ghostrunner.writer")


class GenreContext:
    def __init__(self, genre_slug: str):
        self.slug = genre_slug
        self.data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        p = Path(__file__).resolve().parent.parent / "story" / "genres" / f"{self.slug}.yaml"
        if not p.exists():
            logger.warning("Genre file not found for %s", self.slug)
            return
        with open(p) as f:
            self.data = yaml.safe_load(f)

    @property
    def tone(self) -> str:
        return self.data.get("tone", "Neutral and direct.")

    @property
    def operator_name(self) -> str:
        return self.data.get("operator_callsign", "Operator")

    @property
    def runner_name(self) -> str:
        return self.data.get("runner_callsign", "Runner")


class WriterNode:
    """Uses Ollama to generate dialogue from a drafted Beat."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=60.0)

        # Determine model
        self.model = self.settings.llm_model
        if not self.model:
            # We will use a known model from health checks if empty, e.g. qwen2.5:3b
            self.model = "qwen2.5:3b"

    async def close(self) -> None:
        await self.client.aclose()

    async def write_beat(self, beat: Beat, genre_slug: str, distance_covered_m: float) -> Beat:
        """Hydrates the beat's variants['operator'] using the LLM."""

        genre = GenreContext(genre_slug)
        draft = beat.variants.get("operator", "")

        prompt = f"""
You are writing a localized audio drama for a runner. 
Genre Tone: {genre.tone}
Operator Name: {genre.operator_name}
Runner Name: {genre.runner_name}

Event Type: {beat.kind}
Draft Instruction/Action: "{draft}"
Distance Covered so far: {distance_covered_m:.0f} meters

Write exactly ONE short line of dialogue (1-3 sentences) spoken by {genre.operator_name} over the radio to the {genre.runner_name}.
It MUST convey the information in the Draft Instruction if present.
Do not include any sound effects, markdown, or action tags. Just the spoken words.

Return a JSON object:
{{"dialogue": "the written line here"}}
"""

        try:
            r = await self.client.post(
                f"{self.settings.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
            )
            r.raise_for_status()
            res = r.json()
            response_text = res.get("response", "{}")

            try:
                data = json.loads(response_text)
                dialogue = data.get("dialogue")
                if dialogue:
                    beat.variants["operator"] = dialogue
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM JSON: %s", response_text)

        except Exception as e:
            logger.warning("LLM Writer failed, using fallback draft: %s", e)

        return beat
