"""Slope and aspect as a directional multiplier on spread rate.

F_slope = exp(k_s * tan(slope) * cos(phi)), where phi is the angle between the
direction fire is moving and the uphill direction. Fire runs uphill and
crawls downhill.

The trap: LANDFIRE aspect is the direction the slope FACES, which is
downslope. Uphill is aspect + 180. Getting this backwards puts the fire in
the valley instead of on the ridge and still looks plausible on a map.

The second trap, and the reason `grid_convergence` lives here: aspect is a
GEOGRAPHIC bearing, while a step across the grid is a bearing in EPSG:5070.
Albers is not conformal-with-north, so the two frames differ by the meridian
convergence -- about -15.7 degrees over Paradise. Comparing them directly
rotates every terrain and wind response by that much.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from pyproj import Geod, Transformer

# exp(k_s * tan(slope)) at 20 degrees is ~1.7x, which is roughly the rule of
# thumb that spread rate doubles per 20 degrees of upslope.
K_SLOPE = 1.5

# Steep cells otherwise explode: tan(80 deg) is 5.7, and exp(8.5) is nonsense.
MAX_SLOPE_DEG = 55.0
CLAMP = (0.3, 4.0)

FLAT = -1  # LANDFIRE aspect code for cells with no downslope direction

_GEOD = Geod(ellps="WGS84")
_TO_WGS = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)


@lru_cache(maxsize=32)
def _convergence(x: float, y: float) -> float:
    """True bearing of the grid's +Y axis at one EPSG:5070 point, in degrees."""
    lon0, lat0 = _TO_WGS.transform(x, y)
    lon1, lat1 = _TO_WGS.transform(x, y + 1000.0)
    return _GEOD.inv(lon0, lat0, lon1, lat1)[0]


def grid_convergence(transform, shape_=None) -> float:
    """Degrees between grid north and true north at the centre of a raster.

    A step of one row up the grid points at `grid_convergence` degrees true,
    not at 0. Weather bearings and LANDFIRE aspect are true bearings, so they
    have to come into the grid frame before they meet a step direction:

        bearing_in_grid_frame = geographic_bearing - grid_convergence(...)

    Measured by a pyproj round trip rather than the Albers convergence
    formula, so it stays right if the model CRS ever changes. Roughly -15.7
    degrees over Paradise and -13.8 over the Palisades bbox -- i.e. a due-north
    wind runs up a grid column that is really pointing west of north.

    `shape_` is (rows, cols); without it the transform's origin is used, which
    is within a few hundredths of a degree at these bbox sizes.
    """
    rows, cols = shape_ if shape_ is not None else (0, 0)
    x = transform.c + transform.a * cols / 2
    y = transform.f + transform.e * rows / 2
    return _convergence(round(x, 3), round(y, 3))


def to_grid_bearing(geographic_deg, transform, shape_=None):
    """A true bearing (or array of them) expressed in grid degrees."""
    return (geographic_deg - grid_convergence(transform, shape_)) % 360


def slope_factors(slope_deg: np.ndarray, aspect_deg: np.ndarray,
                  neighbours: list[tuple[int, int]],
                  convergence_deg: float = 0.0) -> np.ndarray:
    """(len(neighbours), rows, cols) of F_slope, one plane per step direction.

    Indexed by the *destination* cell, matching how F_fuel is applied.

    `convergence_deg` rotates LANDFIRE's geographic aspect into the grid frame
    the step bearings are computed in -- see `grid_convergence`. It defaults to
    0 because a synthetic test grid has no projection; every caller working on
    a real raster passes the real value.
    """
    uphill = (aspect_deg.astype("float32") + 180 - convergence_deg) % 360
    flat = aspect_deg == FLAT
    tan_slope = np.tan(np.radians(np.clip(slope_deg, 0, MAX_SLOPE_DEG)))

    factors = np.empty((len(neighbours), *slope_deg.shape), dtype="float32")
    for index, (drow, dcol) in enumerate(neighbours):
        # Row index grows southward, so north is -drow.
        bearing = math.degrees(math.atan2(dcol, -drow)) % 360
        phi = np.radians(bearing - uphill)
        plane = np.exp(K_SLOPE * tan_slope * np.cos(phi))
        plane[flat] = 1.0
        factors[index] = np.clip(plane, *CLAMP)
    return factors


if __name__ == "__main__":
    from . import landfire
    from .spread import NEIGHBOURS

    slope, _ = landfire.fetch("slope")
    aspect, _ = landfire.fetch("aspect")
    factors = slope_factors(slope, aspect, NEIGHBOURS)

    print(f"slope  {slope.min()}-{slope.max()} deg, mean {slope.mean():.1f}")
    print(f"aspect flat cells: {100 * (aspect == FLAT).mean():.1f}%")
    print(f"F_slope {factors.min():.2f}-{factors.max():.2f}, mean {factors.mean():.2f}")

    # A north-facing slope (aspect 0) has uphill to the south, so a southward
    # step must be favoured over a northward one.
    north_facing = (aspect == 0) & (slope > 20)
    south_step = NEIGHBOURS.index((1, 0))
    north_step = NEIGHBOURS.index((-1, 0))
    print(f"north-facing steep cells: {north_facing.sum()}")
    print(f"  uphill (southward) F_slope {factors[south_step][north_facing].mean():.2f}")
    print(f"  downhill (northward)      {factors[north_step][north_facing].mean():.2f}")
