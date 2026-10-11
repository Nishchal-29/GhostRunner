import pytest
from engine.models import Beat
from llm.writer import WriterNode, GenreContext

def test_genre_context():
    g = GenreContext("zombie")
    assert g.operator_name == "Control"
    assert g.runner_name == "Runner"

@pytest.mark.asyncio
async def test_writer_fallback():
    # If LLM is unreachable (e.g. wrong URL), it should fallback to draft
    writer = WriterNode()
    writer.settings.ollama_url = "http://localhost:9999" # invalid

    b = Beat(
        id="b1",
        anchor_chainage_m=0.0,
        expires_chainage_m=10.0,
        kind="NAV",
        priority=100,
        variants={"operator": "Draft"}
    )

    out = await writer.write_beat(b, "spy", 0.0)
    assert out.variants["operator"] == "Draft"
    await writer.close()
