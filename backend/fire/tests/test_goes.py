"""Offline tests for the GOES ABI seed source. No network, no netCDF fixture.

`to_hotspots` is split out of `fetch` precisely so the two things that can go
quietly wrong -- decoding the fire mask and geolocating the cells -- can be
tested against a hand-built grid. The traps here are the day-of-year timestamp
in the filename and the coarse pixel footprint, both of which fail silently:
a misparsed scan time still looks like a plausible timestamp, and a GOES
detection seeded at VIIRS's 375 m lands in a single cell and vanishes.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import goes, spread  # noqa: E402

ACQ = datetime(2026, 9, 19, 20, 1, 17, tzinfo=timezone.utc)

# A 3x3 grid one degree per cell, upper-left corner at (-120, 38), in plain
# EPSG:4326 so the geolocation is checkable by eye.
TRANSFORM = Affine(1.0, 0.0, -120.0, 0.0, -1.0, 38.0)


def _grid(values):
    return np.array(values, dtype=np.int16)


def test_scan_start_reads_day_of_year_not_month_day():
    name = "OR_ABI-L2-FDCC-M6_G18_s20262622001177_e20262622003551_c20262622004042.nc"
    assert goes.scan_start(name) == ACQ


def test_scan_start_rejects_a_name_it_cannot_parse():
    with pytest.raises(goes.GoesError):
        goes.scan_start("something_else.nc")


def test_bucket_follows_the_longitude():
    assert goes.bucket_for(-119.6) == goes.WEST   # California
    assert goes.bucket_for(-80.0) == goes.EAST    # Florida


def test_only_fire_coded_cells_become_hotspots():
    # 0 clear, 5 cloud/water, 10 good fire, 33 temporally filtered high prob.
    mask = _grid([[0, 5, 10], [5, 0, 0], [33, 0, 5]])
    power = np.where(mask > 9, 250.0, 0.0)
    found = goes.to_hotspots(mask, power, TRANSFORM, "EPSG:4326",
                             (-180, -90, 180, 90), ACQ, goes.WEST)
    assert {h.confidence for h in found} == {"h"}
    assert len(found) == 2
    assert all(h.frp == 250.0 for h in found)
    assert all(h.acq_time == ACQ and h.sensor == "ABI/GOES18" for h in found)


def test_mask_codes_map_to_the_confidence_they_mean():
    mask = _grid([[13, 15, 12], [0, 0, 0], [0, 0, 0]])
    found = goes.to_hotspots(mask, np.zeros((3, 3)), TRANSFORM, "EPSG:4326",
                             (-180, -90, 180, 90), ACQ, goes.WEST)
    assert [h.confidence for h in found] == ["h", "l", "n"]  # high, low, cloudy


def test_cells_are_geolocated_to_their_centre_not_their_corner():
    mask = _grid([[10, 0, 0], [0, 0, 0], [0, 0, 0]])
    found = goes.to_hotspots(mask, np.zeros((3, 3)), TRANSFORM, "EPSG:4326",
                             (-180, -90, 180, 90), ACQ, goes.WEST)
    assert found[0].lon == pytest.approx(-119.5)
    assert found[0].lat == pytest.approx(37.5)


def test_cells_outside_the_bbox_are_dropped():
    mask = _grid([[10, 0, 10], [0, 0, 0], [10, 0, 0]])
    tight = (-120.0, 37.0, -119.0, 38.0)  # only the upper-left cell centre
    found = goes.to_hotspots(mask, np.zeros((3, 3)), TRANSFORM, "EPSG:4326",
                             tight, ACQ, goes.WEST)
    assert len(found) == 1
    assert found[0].lon == pytest.approx(-119.5)


def test_an_empty_frame_is_an_empty_list_not_an_error():
    assert goes.to_hotspots(_grid([[0, 0], [0, 5]]), np.zeros((2, 2)), TRANSFORM,
                            "EPSG:4326", (-180, -90, 180, 90), ACQ, goes.WEST) == []


def test_a_goes_seed_covers_more_cells_than_a_viirs_seed():
    """The whole point of per-hotspot pixel_m.

    A 3 km ABI cell seeded at VIIRS's 375 m marks one 120 m grid cell, which
    the morphological closing then drops -- the fresh detection would be
    fetched, geolocated correctly, and silently do nothing.
    """
    mask = _grid([[10, 0, 0], [0, 0, 0], [0, 0, 0]])
    abi = goes.to_hotspots(mask, np.zeros((3, 3)), TRANSFORM, "EPSG:4326",
                           (-180, -90, 180, 90), ACQ, goes.WEST)
    assert abi[0].pixel_m == goes.PIXEL_M

    # 120 m cells in EPSG:5070, the resolution the engine actually runs at,
    # windowed on the detection itself.
    from pyproj import Transformer
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform(
        abi[0].lon, abi[0].lat)
    grid_transform = Affine(120.0, 0.0, x - 24_000, 0.0, -120.0, y + 24_000)
    shape = (400, 400)
    wide = spread.seed_from_hotspots(abi, grid_transform, shape)

    from dataclasses import replace
    narrow = spread.seed_from_hotspots([replace(abi[0], pixel_m=375.0)],
                                       grid_transform, shape)
    assert wide.sum() > narrow.sum() * 4
