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


def test_grid_convergence_is_the_true_bearing_of_a_step_up_the_grid():
    """EPSG:5070 north is not true north, and the gap is not small.

    Measured the way the audit measured it: project a point, step 1 km in +Y,
    and ask pyproj for the geodesic azimuth between the two. About -15.7
    degrees over Paradise -- so a due-north wind was being pointed up a grid
    column that really runs west of north.
    """
    from affine import Affine
    from pyproj import Transformer

    to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    for lon, lat, expected in [(-121.62, 39.76, -15.72), (-118.60, 34.08, -13.83)]:
        x, y = to_albers.transform(lon, lat)
        transform = Affine(120.0, 0.0, x, 0.0, -120.0, y)
        assert terrain.grid_convergence(transform) == pytest.approx(expected, abs=0.05)


def test_convergence_rotates_the_uphill_direction():
    """Aspect is a geographic bearing; the step bearings it meets are not.

    A north-facing cell has uphill due south on the ground. Under a negative
    convergence that lands between the south and south-west grid steps, so the
    south-west plane must gain and the south plane must give some up. Without
    the rotation both stay where an unrotated compass put them.
    """
    slope = np.full((3, 3), 30.0, dtype="float32")
    aspect = np.zeros((3, 3), dtype="float32")

    plain = terrain.slope_factors(slope, aspect, NEIGHBOURS)
    rotated = terrain.slope_factors(slope, aspect, NEIGHBOURS,
                                    convergence_deg=-15.72)
    south = NEIGHBOURS.index((1, 0))
    southwest = NEIGHBOURS.index((1, -1))

    assert rotated[southwest].mean() > plain[southwest].mean()
    assert rotated[south].mean() < plain[south].mean()
