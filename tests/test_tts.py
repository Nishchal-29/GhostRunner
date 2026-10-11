import pytest
from pathlib import Path
from audio.tts import MockTTS, generate_beat_audio
from engine.models import Beat

@pytest.mark.asyncio
async def test_mock_tts():
    tts = MockTTS()
    text = "Hello world, this is a test."
    path, dur = await tts.synthesize(text)

    assert path.exists()
    assert dur > 1.0

    # Cleanup
    path.unlink(missing_ok=True)

@pytest.mark.asyncio
async def test_generate_beat_audio(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "mock")

    b = Beat(
        id="test1",
        anchor_chainage_m=0.0,
        expires_chainage_m=10.0,
        kind="NAV",
        priority=100,
        variants={"operator": "Testing."}
    )

    out = await generate_beat_audio(b)
    assert "operator" in out.audio
    assert "operator" in out.duration_s

    # Cleanup
    p = out.audio["operator"]
    from config import get_settings
    path = get_settings().audio_dir / p
    path.unlink(missing_ok=True)
