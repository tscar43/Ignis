"""The FARSITE-class elliptical baseline, for comparison against this engine.

Why this file exists: there is no public archive of any vendor's fire-spread
prediction for a given historical fire. Technosylva, Wildfire Analyst and the
rest run under contract to agencies and do not publish their polygons, so
"compare against a commercial model" cannot be done from retrievable data.

What *is* public is the model underneath them. FARSITE, FlamMap, Prometheus
and the commercial tools built on that lineage all propagate a fire front as
an ellipse by Huygens' principle, with the length-to-breadth ratio set by wind
speed. Implementing that formulation honestly gives a baseline that is
recognisably the industry standard, and is clearly *not* a claim about what
any particular vendor's product would have produced.

The ellipse, from Finney (1998), FARSITE eq. 8, after Alexander (1985):

    LB = 0.936 e^(0.2566 U) + 0.461 e^(-0.1548 U) - 0.397,  U in m/s, LB <= 8
    HB = (LB + sqrt(LB^2 - 1)) / (LB - sqrt(LB^2 - 1))

with the ignition at the rear focus, so the spread rate in a direction theta
off the wind is

    R(theta) / R_head = (1 - e) / (1 - e cos theta),   e = sqrt(LB^2 - 1) / LB

which gives R(0) = R_head and R(180) = R_head / HB by construction.

Run through `spread.arrival_times` via its `step_factors` hook, so the solver,
the grid, the seed and the calibration are identical to the main model and the
only thing that differs is the shape of the wind term.
"""

from __future__ import annotations

import math

from .spread import NEIGHBOURS

# FARSITE's U is midflame wind; ours is the 10 m open wind every weather feed
# reports. 0.4 is the standard unsheltered adjustment (Albini 1976, Rothermel
# 1983). It matters more than it looks: without it, 35 km/h drives LB straight
# into the cap and the ellipse turns into a line.
MIDFLAME_FACTOR = 0.4
LB_CAP = 8.0  # FARSITE's own limit


def length_to_breadth(wind_kmh: float) -> float:
    """Alexander's LB ratio for a 10 m open wind in km/h."""
    u = wind_kmh / 3.6 * MIDFLAME_FACTOR
    lb = 0.936 * math.exp(0.2566 * u) + 0.461 * math.exp(-0.1548 * u) - 0.397
    return min(max(lb, 1.0), LB_CAP)


def eccentricity(lb: float) -> float:
    return math.sqrt(lb * lb - 1.0) / lb if lb > 1.0 else 0.0


def head_to_back(wind_kmh: float) -> float:
    """Head:back rate ratio, the other form the literature quotes."""
    e = eccentricity(length_to_breadth(wind_kmh))
    return (1 + e) / (1 - e) if e < 1 else math.inf


def step_factors(wind_kmh: float, wind_toward_deg: float) -> list[float]:
    """R(theta)/R_head per NEIGHBOURS direction. Same shape `_step_propensity` returns.

    Row index grows southward, so north is -drow -- the bearing convention has
    to match `spread._step_propensity` exactly or the ellipse points the wrong
    way while still looking like a plausible fire.
    """
    e = eccentricity(length_to_breadth(wind_kmh))
    factors = []
    for drow, dcol in NEIGHBOURS:
        bearing = math.degrees(math.atan2(dcol, -drow)) % 360
        theta = math.radians(bearing - wind_toward_deg)
        factors.append((1 - e) / (1 - e * math.cos(theta)))
    return factors


if __name__ == "__main__":
    print(f"{'wind km/h':>10} {'LB':>6} {'head:back':>10} {'head:flank':>11}")
    for wind in (5, 10, 20, 35, 50, 80):
        lb = length_to_breadth(wind)
        e = eccentricity(lb)
        flank = (1 - e) / 1.0  # theta = 90, cos theta = 0
        print(f"{wind:>10} {lb:>6.2f} {head_to_back(wind):>10.1f} "
              f"{1 / flank:>10.1f}:1")
