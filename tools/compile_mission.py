"""CLI script to test the mission compilation graph."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.store import Store
from pipeline.compile import run_compiler
from config import get_settings


async def main():
    store = Store()
    await store.connect()

    settings = get_settings()
    session_id = f"test_sim_{uuid.uuid4().hex[:8]}"
    genre = "cyberpunk"
    params = {
        "start_lat": settings.demo_start_lat,
        "start_lon": settings.demo_start_lon,
        "distance_m": 1000.0
    }

    await store.create_session(session_id, genre, params)

    print(f"Compiling mission {session_id}...")
    try:
        await run_compiler(session_id, genre, params, store)

        session = await store.get_session(session_id)
        print(f"Session status: {session['status']}")

        mission = await store.get_mission(session_id)
        if mission:
            print(f"Mission route length: {mission['stats']['length_m']:.1f} m")
            print(f"Mission maneuvers: {mission['stats']['maneuvers']}")
            print(f"Mission landmarks: {mission['stats']['landmarks']}")
            print(f"Mission intro beat generated: {len(mission['beats']) > 0}")
    except Exception as e:
        print(f"Compilation failed: {e}")
    finally:
        await store.close()

if __name__ == "__main__":
    asyncio.run(main())
