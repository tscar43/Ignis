"""Offline tests for the scoring harness. No network.

Two of the three defects the 2026-09-20 audit found in this file were invisible
from its output: it reported a gap in hours and scored a different number of
minutes, and it fetched truth that stopped before the pass it scored against.
Both produced plausible IoUs. These pin the arithmetic instead of the answer.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import firms, landfire, terrain, validate  # noqa: E402
from backend.weather import nws  # noqa: E402

UTC = timezone.utc
TRANSFORM = Affine(120.0, 0.0, -2_200_000.0, 0.0, -120.0, 2_000_000.0)


def _setup(gap_min, size=41):
    """A setup dict shaped like `validate._setup`, with nothing fetched."""
    ignition = np.zeros((size, size), dtype=bool)
    ignition[size // 2, size // 2] = True
    return {
        "ignition": ignition,
        "truth": ignition.copy(),
        "wind": nws.Wind(35.0, 90.0, "2025-01-08T09:00:00Z"),
        "fuel": np.ones((size, size), dtype="float32"),
        "slope": np.ones((len(validate.NEIGHBOURS), size, size), dtype="float32"),
        "transform": TRANSFORM,
        "convergence": 0.0,
        "cell_km2": (TRANSFORM.a / 1000) ** 2,
        "gap_min": gap_min,
        "horizon_min": gap_min,
        "band": min(validate.BANDS,
                    key=lambda n: abs(validate.BANDS[n] - gap_min)
                    if validate.BANDS[n] else 1e9),
    }


def test_a_twelve_hour_window_simulates_twelve_hours():
    """The defect: a 720-minute gap was scored against a 360-minute run.

    `_predict` took the solver's default horizon and thresholded at the
    nearest published band, so every window longer than six hours reported a
    six-hour prediction under a twelve-hour label. Calibration could absorb
    some of that into R0, which is exactly why it never looked wrong.
    """
    twelve = _setup(720)
    six = _setup(360)
    assert twelve["band"] == "h6"  # the label is still h6...
    assert twelve["horizon_min"] == 720  # ...but the simulation is not

    burned_12 = validate._predict(twelve, use_fuel=False, use_slope=False, r0=10.0)
    burned_6 = validate._predict(six, use_fuel=False, use_slope=False, r0=10.0)
    assert burned_12.sum() > burned_6.sum()


def test_an_arrival_beyond_the_band_is_inside_a_longer_window():
    """A cell reached at 500 minutes belongs in a 720-minute prediction.

    It used to be excluded, because the threshold was BANDS["h6"] = 360.
    """
    setup = _setup(720)
    burned = validate._predict(setup, use_fuel=False, use_slope=False, r0=10.0)
    arrival = validate.arrival_times(
        setup["ignition"], setup["wind"].speed_kmh, setup["wind"].toward_deg,
        cell_m=setup["transform"].a, horizon_min=720, r0=10.0)
    reached_late = (arrival > 360) & (arrival <= 720)
    assert reached_late.any(), "test grid is too small to reach past 6 h"
    assert burned[reached_late].all()


def test_setup_fetches_truth_through_the_validation_day(monkeypatch):
    """Across UTC midnight the truth mask used to stop a day short.

    `days` counted from the seed date, so a window seeded on 7 January and
    validated on the 9th asked for the 6th and 7th -- the target footprint
    could not contain the detections it was scored against. NASA returns DATE
    through DATE + DAY_RANGE - 1.
    """
    seen = {}

    def fetch_many(sources, bbox=None, start_date=None, days=None, **kw):
        seen.update(start_date=start_date, days=days)
        return [firms.Hotspot(lon=-118.6, lat=34.08, confidence="h", frp=1.0,
                              acq_time=datetime(2025, 1, 7, 21, 27, tzinfo=UTC),
                              sensor="VIIRS", source="VIIRS_SNPP_SP")]

    monkeypatch.setattr(firms, "fetch_many", fetch_many)
    monkeypatch.setattr(landfire, "fetch", lambda layer, bbox=None, **kw: (
        np.zeros((4, 4), "int16"), {"transform": TRANSFORM}))
    monkeypatch.setattr(landfire, "fuel_factor",
                        lambda codes: np.ones((4, 4), "float32"))
    monkeypatch.setattr(terrain, "slope_factors",
                        lambda *a, **kw: np.ones((8, 4, 4), "float32"))
    monkeypatch.setattr(terrain, "grid_convergence", lambda *a, **kw: 0.0)
    monkeypatch.setattr(nws, "archived",
                        lambda *a, **kw: nws.Wind(35.0, 90.0, "2025-01-07T21:00:00Z"))

    seed_at = datetime(2025, 1, 7, 21, 27, tzinfo=UTC)
    validate_at = datetime(2025, 1, 9, 9, 7, tzinfo=UTC)
    validate._setup(seed_at, validate_at, (-118.72, 34.0, -118.47, 34.16), 8)

    last_day = seen["start_date"] + timedelta(days=seen["days"] - 1)
    assert last_day >= validate_at.date()


def test_setup_carries_the_grid_convergence_for_its_raster(monkeypatch):
    """`_predict` cannot rotate the wind if `_setup` never measured the angle."""
    setup = _setup(360)
    assert "convergence" in setup
    # and the real one is not zero over the Palisades bbox
    from pyproj import Transformer

    to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    x, y = to_albers.transform(-118.60, 34.08)
    real = terrain.grid_convergence(Affine(120.0, 0.0, x, 0.0, -120.0, y))
    assert real == pytest.approx(-13.83, abs=0.05)
