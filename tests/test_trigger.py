import pytest
from engine.models import RouteModel, Maneuver, Landmark
from pipeline.nodes.trigger import TriggerContext, determine_next_beat

@pytest.fixture
def mock_route():
    return RouteModel(
        length_m=1000.0,
        points=[(40.0, -74.0), (40.001, -74.0)],
        utm_epsg=32618,
        maneuvers=[
            Maneuver(chainage_m=100.0, type="right", instruction="Turn right on Oak St"),
            Maneuver(chainage_m=500.0, type="left", instruction="Turn left")
        ],
        landmarks=[
            Landmark(id="1", name="Statue", kind="monument", lat=40.0, lon=-74.0, chainage_m=200.0, side="left", offset_m=10.0)
        ]
    )

def test_trigger_nav(mock_route):
    ctx = TriggerContext(
        route=mock_route,
        current_chainage_m=40.0,
        speed_mps=3.0,
        played_events=[],
        last_beat_chainage_m=0.0
    )
    beat = determine_next_beat(ctx)
    assert beat is not None
    assert beat.kind == "NAV"
    assert "nav_" in beat.id

def test_trigger_played_filtering(mock_route):
    # NAV is at 100.0, we simulate we already played it
    ctx = TriggerContext(
        route=mock_route,
        current_chainage_m=40.0,
        speed_mps=3.0,
        played_events=[{"beat_id": "nav_100.0_right"}],
        last_beat_chainage_m=0.0
    )
    beat = determine_next_beat(ctx)
    assert beat is None  # Neither NAV (played) nor TENSION (dist < 120) nor LANDMARK (at 200)

def test_trigger_landmark(mock_route):
    ctx = TriggerContext(
        route=mock_route,
        current_chainage_m=160.0,
        speed_mps=3.0,
        played_events=[{"beat_id": "nav_100.0_right"}],
        last_beat_chainage_m=100.0
    )
    beat = determine_next_beat(ctx)
    assert beat is not None
    assert beat.kind == "LANDMARK"

def test_trigger_tension(mock_route):
    # No maneuvers or landmarks nearby, far from last beat
    ctx = TriggerContext(
        route=mock_route,
        current_chainage_m=350.0,
        speed_mps=3.0,
        played_events=[{"beat_id": "nav_100.0_right"}, {"beat_id": "lm_1"}],
        last_beat_chainage_m=200.0
    )
    beat = determine_next_beat(ctx)
    assert beat is not None
    assert beat.kind == "TENSION"
