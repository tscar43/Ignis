"""Offline tests for the arrival-time spread. No network.

These guard the two things Backend's routing depends on: wind pushes the fire
the way the contract says it does, and the bands nest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import spread  # noqa: E402

CELL = 100.0


def _single_seed(size=41):
    ignition = np.zeros((size, size), dtype=bool)
    ignition[size // 2, size // 2] = True
    return ignition


def test_fire_runs_downwind_not_upwind():
    """wind_toward=90 is due east, so east must be reached before west."""
    ignition = _single_seed()
    arrival = spread.arrival_times(ignition, wind_kmh=40, wind_toward_deg=90,
                                   cell_m=CELL)
    mid = ignition.shape[0] // 2
    east, west = arrival[mid, mid + 5], arrival[mid, mid - 5]
    assert east < west, f"east {east} should beat west {west}"
    assert west / east > 3, "head should clearly outrun the back"


def test_every_compass_direction_maps_to_the_right_neighbour():
    """A wrong sign on drow flips north and south and nobody notices."""
    mid = 20
    for toward, (drow, dcol) in [(0, (-1, 0)), (90, (0, 1)),
                                 (180, (1, 0)), (270, (0, -1))]:
        arrival = spread.arrival_times(_single_seed(), wind_kmh=40,
                                       wind_toward_deg=toward, cell_m=CELL)
        downwind = arrival[mid + drow * 5, mid + dcol * 5]
        upwind = arrival[mid - drow * 5, mid - dcol * 5]
        assert downwind < upwind, f"toward={toward} spread the wrong way"


def test_zero_propensity_is_a_hard_barrier():
    ignition = _single_seed()
    propensity = np.ones(ignition.shape, dtype="float32")
    propensity[:, 25:] = 0.0  # wall across the path
    arrival = spread.arrival_times(ignition, wind_kmh=40, wind_toward_deg=90,
                                   cell_m=CELL, propensity=propensity)
    assert np.isinf(arrival[:, 25:]).all(), "fire entered a non-burnable cell"


def test_bands_nest_after_polygonizing():
    ignition = _single_seed()
    arrival = spread.arrival_times(ignition, wind_kmh=30, wind_toward_deg=240,
                                   cell_m=CELL)
    # north-up transform, origin at a plausible Albers coordinate
    transform = Affine(CELL, 0, -2_000_000, 0, -CELL, 2_000_000)
    result = spread.bands_to_geojson(arrival, transform)

    areas = result["area_km2"]
    assert areas["current"] <= areas["h1"] <= areas["h3"] <= areas["h6"]
    assert areas["h6"] > areas["current"], "nothing spread at all"

    from shapely.geometry import shape as to_shape
    from shapely.ops import unary_union

    bands = {name: unary_union([to_shape(f["geometry"]) for f in fc["features"]])
             for name, fc in result["risk_polygons"].items()}
    for inner, outer in [("current", "h1"), ("h1", "h3"), ("h3", "h6")]:
        leaked = bands[inner].difference(bands[outer]).area
        assert leaked < 1e-15, f"{outer} must contain {inner} (leaked {leaked:.3g})"


def test_output_is_lon_lat_degrees():
    arrival = spread.arrival_times(_single_seed(), wind_kmh=30,
                                   wind_toward_deg=240, cell_m=CELL)
    transform = Affine(CELL, 0, -2_000_000, 0, -CELL, 2_000_000)
    fc = spread.bands_to_geojson(arrival, transform)["risk_polygons"]["h6"]
    lon, lat = fc["features"][0]["geometry"]["coordinates"][0][0]
    assert -180 <= lon <= 180 and -90 <= lat <= 90
    assert lon < 0 < lat, "coordinates must be [lon, lat] in CONUS"
