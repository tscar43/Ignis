"""Tests for the contract validator. No network.

Each test breaks one rule in a known-good payload and asserts the validator
notices. A validator that never fails is worse than none, because it gets
trusted.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import contract  # noqa: E402

DEMO = Path(__file__).resolve().parents[3] / "demo_data" / "risk_demo.json"


@pytest.fixture
def payload():
    return json.loads(DEMO.read_text(encoding="utf-8"))


def test_the_shipped_demo_payload_is_valid(payload):
    assert contract.validate(payload) == []


def test_swapped_lat_lon_is_caught(payload):
    point = payload["fire_points"]["features"][0]["geometry"]
    lon, lat = point["coordinates"]
    point["coordinates"] = [lat, lon]  # -121 as a latitude
    assert any("[lon, lat]" in p for p in contract.validate(payload))


def test_non_cumulative_bands_are_caught(payload):
    """Swapping h1 and h6 makes the inner band the larger one."""
    bands = payload["risk_polygons"]
    bands["h1"], bands["h6"] = bands["h6"], bands["h1"]
    assert any("must contain" in p for p in contract.validate(payload))


def test_a_band_that_is_a_ring_not_a_region_is_caught(payload):
    """The classic misread: h3 drawn as the area between h1 and h6.

    It looks right on a map and breaks routing, because a point inside h1
    is then not inside h3.
    """
    from shapely.geometry import mapping
    from shapely.geometry import shape as to_shape
    from shapely.ops import unary_union

    def merge(name):
        return unary_union([to_shape(f["geometry"])
                            for f in payload["risk_polygons"][name]["features"]])

    ring = merge("h6").difference(merge("h1"))
    payload["risk_polygons"]["h3"] = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(part), "properties": {"band": "h3"}}
        for part in (ring.geoms if ring.geom_type == "MultiPolygon" else [ring])]}

    assert any("h3 must contain h1" in p for p in contract.validate(payload))


def test_missing_timestamp_is_caught(payload):
    del payload["data_as_of"]["firms"]
    assert any("firms" in p for p in contract.validate(payload))


def test_naive_timestamp_without_z_is_caught(payload):
    payload["generated_at"] = "2026-09-19 14:00:00"
    assert any("generated_at" in p for p in contract.validate(payload))


def test_wind_bearing_out_of_range_is_caught(payload):
    payload["summary"]["wind_toward_deg"] = 400
    assert any("wind_toward_deg" in p for p in contract.validate(payload))


def test_reported_area_that_disagrees_with_the_polygons_is_caught(payload):
    payload["summary"]["area_km2"]["h6"] *= 3
    assert any("polygons measure" in p for p in contract.validate(payload))


def test_decreasing_areas_are_caught(payload):
    payload["summary"]["area_km2"]["h6"] = 0.1
    assert any("must not decrease" in p for p in contract.validate(payload))


def test_missing_top_level_key_is_caught(payload):
    del payload["risk_polygons"]
    assert contract.validate(payload) == ["missing top-level key 'risk_polygons'"]


def test_check_raises_and_passes_through(payload):
    assert contract.check(payload) is payload
    broken = copy.deepcopy(payload)
    del broken["summary"]
    with pytest.raises(ValueError, match="violates the contract"):
        contract.check(broken)
