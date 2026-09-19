"""Slope and aspect as a directional multiplier on spread rate.

F_slope = exp(k_s * tan(slope) * cos(phi)), where phi is the angle between the
direction fire is moving and the uphill direction. Fire runs uphill and
crawls downhill.

The trap: LANDFIRE aspect is the direction the slope FACES, which is
downslope. Uphill is aspect + 180. Getting this backwards puts the fire in
the valley instead of on the ridge and still looks plausible on a map.
"""

from __future__ import annotations

import math

import numpy as np

# exp(k_s * tan(slope)) at 20 degrees is ~1.7x, which is roughly the rule of
# thumb that spread rate doubles per 20 degrees of upslope.
K_SLOPE = 1.5

# Steep cells otherwise explode: tan(80 deg) is 5.7, and exp(8.5) is nonsense.
MAX_SLOPE_DEG = 55.0
CLAMP = (0.3, 4.0)

FLAT = -1  # LANDFIRE aspect code for cells with no downslope direction


def slope_factors(slope_deg: np.ndarray, aspect_deg: np.ndarray,
                  neighbours: list[tuple[int, int]]) -> np.ndarray:
    """(len(neighbours), rows, cols) of F_slope, one plane per step direction.

    Indexed by the *destination* cell, matching how F_fuel is applied.
    """
    uphill = (aspect_deg.astype("float32") + 180) % 360
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
