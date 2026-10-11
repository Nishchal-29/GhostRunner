"""CLI script to test Overpass fetch and POI snapping."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.pois import OverpassClient, enrich_route_with_pois
from engine.store import Store
from engine.route_model import build_route_model
from engine.models import Maneuver


async def main():
    store = Store()
    await store.connect()

    # Times square to Bryant park (approx)
    pts = [
        (40.7580, -73.9855),
        (40.7536, -73.9832)
    ]
    model = build_route_model(pts, [])

    client = OverpassClient()
    print("Fetching POIs...")
    try:
        await enrich_route_with_pois(store, client, model)
    except Exception as e:
        print(f"Failed: {e}")
        await client.close()
        await store.close()
        return

    print(f"Found {len(model.landmarks)} landmarks near route.")
    for lm in model.landmarks[:10]:
        print(f"  [{lm.chainage_m:6.1f}m] {lm.side:<5} {lm.offset_m:4.1f}m : {lm.name} ({lm.kind})")

    await client.close()
    await store.close()

if __name__ == "__main__":
    asyncio.run(main())
