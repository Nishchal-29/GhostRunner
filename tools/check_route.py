"""CLI script to verify route loop generation."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.routing import ValhallaClient, generate_loop, decode_and_map_maneuvers, _get_overlap_ratio
from engine.route_model import build_route_model


async def main():
    client = ValhallaClient()

    start = (40.7580, -73.9855) # Times square
    distance = 2000.0

    print(f"Generating loop of {distance}m from {start}...")
    try:
        raw = await generate_loop(client, start, distance)
    except Exception as e:
        print(f"Failed: {e}")
        await client.close()
        return

    pts, maneuvers = decode_and_map_maneuvers(raw)

    model = build_route_model(pts, maneuvers)

    overlap = _get_overlap_ratio(pts, model.utm_epsg)

    print(f"Route Length: {model.length_m:.1f} m")
    print(f"Maneuvers: {len(model.maneuvers)}")
    print(f"Overlap Ratio: {overlap:.3f}")

    print("\nFirst 5 maneuvers:")
    for m in model.maneuvers[:5]:
        print(f"  [{m.chainage_m:6.1f}m] {m.type}: {m.instruction} (Street: {m.street})")

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
