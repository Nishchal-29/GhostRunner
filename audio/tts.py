"""Text-to-Speech synthesis node."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Protocol

import httpx
from mutagen.mp3 import MP3

from config import get_settings
from engine.models import Beat

logger = logging.getLogger("ghostrunner.tts")


class TTSProvider(Protocol):
    async def synthesize(self, text: str, voice_id: str | None = None) -> tuple[Path, float]:
        """Synthesize text into an audio file. Returns (file_path, duration_seconds)."""


class MockTTS:
    """Mock TTS that generates a fake audio file (or just calculates dummy duration)."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def synthesize(self, text: str, voice_id: str | None = None) -> tuple[Path, float]:
        filename = f"{uuid.uuid4().hex[:12]}.mp3"
        out_path = self.settings.audio_dir / filename

        # We don't have a real MP3 here, so we just calculate duration by text length
        # Roughly 12 chars per second
        duration = max(1.0, len(text) / 12.0)

        # Touch the file
        out_path.write_bytes(b"")

        return out_path, duration


class ElevenLabsTTS:
    """ElevenLabs real TTS."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self.client.aclose()

    async def synthesize(self, text: str, voice_id: str | None = None) -> tuple[Path, float]:
        if not voice_id:
            # Default to some standard ID if none provided
            voice_id = "EXAVITQu4vr4xnSDxMaL" # Bella

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": self.settings.elevenlabs_api_key,
            "Content-Type": "application/json"
        }
        data = {
            "text": text,
            "model_id": self.settings.elevenlabs_model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        filename = f"{uuid.uuid4().hex[:12]}.mp3"
        out_path = self.settings.audio_dir / filename

        try:
            r = await self.client.post(url, json=data, headers=headers)
            r.raise_for_status()

            with open(out_path, "wb") as f:
                f.write(r.content)

            # Read actual duration
            audio = MP3(out_path)
            duration = audio.info.length
            return out_path, duration

        except Exception as e:
            logger.error("ElevenLabs TTS failed: %s", e)
            raise


async def generate_beat_audio(beat: Beat) -> Beat:
    """Takes a Beat, generates audio for its variants, and updates it."""
    settings = get_settings()

    if settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key:
        provider: TTSProvider = ElevenLabsTTS()
    else:
        provider = MockTTS()

    # In a real app we might load genre voice_id
    voice_id = None

    try:
        for speaker, text in beat.variants.items():
            path, dur = await provider.synthesize(text, voice_id)
            beat.audio[speaker] = path.name
            beat.duration_s[speaker] = dur
    finally:
        if isinstance(provider, ElevenLabsTTS):
            await provider.close()

    return beat
