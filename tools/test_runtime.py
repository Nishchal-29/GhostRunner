"""Create a fake session and run the compiler so the WS can load it."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.store import Store
from pipeline.compile import run_compiler

async def main():
    store = Store()
    await store.connect()

    session_id = "demo_session"
    genre = "spy"
    params = {"start_lat": 40.7580, "start_lon": -73.9855, "distance_m": 1500.0}

    print("Ensuring tables...")
    await store.ensure_tables()

    print("Creating session demo_session...")
    await store.create_session(session_id, genre, params)

    print("Compiling mission...")
    await run_compiler(session_id, genre, params, store)

    print("Mission compiled! You can now start `python -m app.run` and connect via http://localhost:8000/static/")
    await store.close()

if __name__ == "__main__":
    asyncio.run(main())
