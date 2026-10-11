"""CLI script to test the LLM writer."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.writer import WriterNode
from engine.models import Beat


async def main():
    writer = WriterNode()

    # Test a NAV beat
    b1 = Beat(
        id="test_1",
        anchor_chainage_m=100.0,
        expires_chainage_m=150.0,
        kind="NAV",
        priority=100,
        variants={"operator": "In 80 meters, turn left on Broadway"}
    )

    print("Testing Cyberpunk NAV...")
    out1 = await writer.write_beat(b1, "cyberpunk", distance_covered_m=500.0)
    print(f"Draft : In 80 meters, turn left on Broadway")
    print(f"Result: {out1.variants['operator']}")
    print("-" * 40)

    # Test a LANDMARK beat
    b2 = Beat(
        id="test_2",
        anchor_chainage_m=200.0,
        expires_chainage_m=280.0,
        kind="LANDMARK",
        priority=80,
        variants={"operator": "Approaching Empire State Building on your left."}
    )

    print("Testing Zombie LANDMARK...")
    out2 = await writer.write_beat(b2, "zombie", distance_covered_m=1200.0)
    print(f"Draft : Approaching Empire State Building on your left.")
    print(f"Result: {out2.variants['operator']}")
    print("-" * 40)

    await writer.close()

if __name__ == "__main__":
    asyncio.run(main())
