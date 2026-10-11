"""CLI script to test TTS generation."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.tts import generate_beat_audio
from engine.models import Beat


async def main():
    b = Beat(
        id="test_tts",
        anchor_chainage_m=100.0,
        expires_chainage_m=200.0,
        kind="NAV",
        priority=100,
        variants={"operator": "Approaching intersection. Turn left."}
    )

    print(f"Generating audio for: {b.variants['operator']}")
    out = await generate_beat_audio(b)

    print("Audio file:", out.audio.get("operator"))
    print(f"Duration: {out.duration_s.get('operator'):.2f} s")

if __name__ == "__main__":
    asyncio.run(main())
