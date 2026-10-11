import asyncio
import pytest
from engine.models import RouteModel
from engine.simulator import Simulator


@pytest.fixture
def mock_route():
    # 2 points, 1000m approx distance
    # A fake route where the first two points are far enough
    return RouteModel(
        length_m=100.0,
        points=[(40.0, -74.0), (40.001, -74.0)],
        utm_epsg=32618,
        maneuvers=[],
        landmarks=[]
    )


@pytest.mark.asyncio
async def test_simulator_basic(mock_route):
    queue = asyncio.Queue()
    sim = Simulator(mock_route, queue, base_speed_mps=10.0)
    sim.speed_mult = 1.0  # Real time
    sim.update_interval_s = 0.1  # Fast ticks for test

    sim.start()

    # Wait for a couple of fixes
    fix1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    fix2 = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert fix1 is not None
    assert fix2 is not None

    # Check chainage increments appropriately
    # 10 mps * 1.0 * 0.1s = 1.0m per tick
    assert fix1.lat != fix2.lat or fix1.lon != fix2.lon

    sim.stop()
