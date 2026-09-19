"""Offline tests for F_slope. No network.

The aspect flip is the one that matters: get it backwards and the fire runs
downhill into the valley, which still looks plausible on a map.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import terrain  # noqa: E402
from backend.fire.spread import NEIGHBOURS  # noqa: E402

NORTH = NEIGHBOURS.index((-1, 0))
SOUTH = NEIGHBOURS.index((1, 0))
EAST = NEIGHBOURS.index((0, 1))


def _uniform(slope_deg, aspect_deg, size=3):
    return (np.full((size, size), slope_deg, dtype="int16"),
            np.full((size, size), aspect_deg, dtype="int16"))


def test_fire_runs_uphill_not_downhill():
    """Aspect 0 faces north, so uphill is south."""
    slope, aspect = _uniform(30, 0)
    factors = terrain.slope_factors(slope, aspect, NEIGHBOURS)
    assert factors[SOUTH][1, 1] > 1.0, "uphill should speed fire up"
    assert factors[NORTH][1, 1] < 1.0, "downhill should slow fire down"
    assert factors[SOUTH][1, 1] > factors[NORTH][1, 1]


def test_aspect_is_downslope_facing_not_uphill():
    """A south-facing slope (aspect 180) must favour northward spread.

    This is the assertion that fails if someone drops the +180.
    """
    slope, aspect = _uniform(30, 180)
    factors = terrain.slope_factors(slope, aspect, NEIGHBOURS)
    assert factors[NORTH][1, 1] > factors[SOUTH][1, 1]


def test_cross_slope_is_neutral():
    slope, aspect = _uniform(30, 0)  # uphill due south
    factors = terrain.slope_factors(slope, aspect, NEIGHBOURS)
    assert factors[EAST][1, 1] == pytest.approx(1.0)  # float32, cos(90) isn't exactly 0


def test_flat_cells_have_no_slope_effect():
    slope, aspect = _uniform(0, terrain.FLAT)
    factors = terrain.slope_factors(slope, aspect, NEIGHBOURS)
    assert (factors == 1.0).all()


def test_steep_cells_are_clamped_not_exponential():
    slope, aspect = _uniform(85, 0)  # beyond MAX_SLOPE_DEG
    factors = terrain.slope_factors(slope, aspect, NEIGHBOURS)
    assert factors.max() <= terrain.CLAMP[1]
    assert factors.min() >= terrain.CLAMP[0]
    assert np.isfinite(factors).all()
