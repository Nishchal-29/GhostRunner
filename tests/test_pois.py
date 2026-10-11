import pytest
import h3
from engine.pois import map_poi_kind, extract_poi_name, get_route_cells

def test_map_poi_kind():
    assert map_poi_kind({"amenity": "cafe"}) == "cafe"
    assert map_poi_kind({"historic": "monument", "tourism": "museum"}) == "historic"
    assert map_poi_kind({"random": "tag"}) == "unknown"

def test_extract_name():
    assert extract_poi_name({"name": "Central Park"}) == "Central Park"
    assert extract_poi_name({"name:en": "The Park", "name": "Le Parc"}) == "The Park"
    assert extract_poi_name({"amenity": "cafe"}) is None

def test_get_route_cells():
    # Two points close to each other
    pts = [(40.7580, -73.9855), (40.7581, -73.9856)]
    cells = get_route_cells(pts, resolution=9)
    assert len(cells) > 0
    # Center should be in the cells
    center = h3.latlng_to_cell(40.7580, -73.9855, 9)
    # The grid_disk expansion guarantees center is there if it was one of the points
    assert center in cells
