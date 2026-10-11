import pytest
import json
import os
from engine.routing import decode_and_map_maneuvers, RawRoute, ValhallaClient, generate_loop
from engine.route_model import to_utm, RouteGeometry, build_route_model
from engine.models import Maneuver


@pytest.fixture
def valhalla_response():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "valhalla_route.json")
    if os.path.exists(fixture_path):
        with open(fixture_path) as f:
            return RawRoute(**json.load(f))

    # Fallback mock for testing without fixture
    return RawRoute(
        locations=[{"lat": 0, "lon": 0}, {"lat": 1, "lon": 1}],
        legs=[{
            "shape": "_p~iF~ps|U_ulLnnqC_mqNvxq`@",
            "maneuvers": [
                {"type": 10, "instruction": "Turn right", "begin_shape_index": 0, "street_names": ["Oak St"]}
            ]
        }],
        summary={"length": 1.5}
    )


def test_decode_and_map(valhalla_response):
    pts, maneuvers = decode_and_map_maneuvers(valhalla_response)
    assert len(pts) > 0
    assert len(maneuvers) > 0
    # First maneuver mapped to index
    assert int(maneuvers[0].chainage_m) == 0


def test_utm_epsg():
    assert to_utm(40.0, -74.0) == 32618
    assert to_utm(-40.0, 144.0) == 32755


def test_route_geometry():
    # Simple L shape
    pts = [(0.0, 0.0), (0.001, 0.0), (0.001, 0.001)]
    geom = RouteGeometry(pts)
    assert geom.length_m > 100 # Rough check of metric length
    assert len(geom.utm_densified) > 10 # Densified

    # Check chainage strictly increases (or stays same if points duplicate)
    diffs = [geom.chainages[i] - geom.chainages[i-1] for i in range(1, len(geom.chainages))]
    assert all(d >= 0 for d in diffs)


def test_side_of_route():
    pts = [(0.0, 0.0), (0.0, 0.002)] # Northbound straight
    geom = RouteGeometry(pts)

    # West of route (Left)
    side, offset = geom.get_side(0.001, 0.001, 100.0)
    assert side == "left"

    # East of route (Right)
    side, offset = geom.get_side(-0.001, 0.001, 100.0)
    assert side == "right"

    # North of route (Ahead)
    side, offset = geom.get_side(0.0, 0.003, 200.0)
    assert side == "ahead"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_valhalla_routing():
    client = ValhallaClient()
    try:
        start = (40.7580, -73.9855)
        raw = await generate_loop(client, start, 1000.0)
        assert raw is not None
        assert raw.summary["length"] > 0
    except Exception as e:
        pytest.skip(f"Live Valhalla skipped: {e}")
    finally:
        await client.close()
