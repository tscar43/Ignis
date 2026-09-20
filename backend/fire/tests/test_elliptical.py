"""Offline tests for the FARSITE-class elliptical baseline. No network.

The trap this file exists for is the bearing convention. `step_factors` has to
index NEIGHBOURS exactly the way `spread._step_propensity` does; get it wrong
and the ellipse points somewhere other than downwind, which on a map still
looks like a fire and silently invalidates every comparison drawn against it.
The published identities -- R(0) = head, R(180) = head/HB -- are pinned too,
since a baseline that quietly stops matching the literature is worse than no
baseline at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import elliptical, spread  # noqa: E402


def test_length_to_breadth_grows_with_wind_and_stops_at_the_cap():
    calm, breezy, gale = (elliptical.length_to_breadth(w) for w in (0, 20, 200))
    assert calm < breezy < gale
    assert calm == pytest.approx(1.0, abs=0.01)   # a circle in still air
    assert gale == elliptical.LB_CAP


def test_head_to_back_matches_the_length_to_breadth_identity():
    """HB = (LB + sqrt(LB^2-1)) / (LB - sqrt(LB^2-1)), via the eccentricity."""
    for wind in (5, 20, 35, 60):
        lb = elliptical.length_to_breadth(wind)
        root = (lb * lb - 1) ** 0.5
        assert elliptical.head_to_back(wind) == pytest.approx(
            (lb + root) / (lb - root), rel=1e-9)


def test_the_ellipse_points_downwind_not_upwind():
    """The same flip that `test_nws.py` and the aspect tests guard elsewhere."""
    factors = elliptical.step_factors(35.0, 90.0)  # wind blowing toward the east
    fastest = spread.NEIGHBOURS[max(range(len(factors)), key=factors.__getitem__)]
    slowest = spread.NEIGHBOURS[min(range(len(factors)), key=factors.__getitem__)]
    assert fastest == (0, 1)    # east: same row, next column
    assert slowest == (0, -1)   # west, directly upwind


def test_head_is_unity_and_back_is_the_head_to_back_ratio():
    wind = 35.0
    factors = dict(zip(spread.NEIGHBOURS, elliptical.step_factors(wind, 90.0)))
    assert factors[(0, 1)] == pytest.approx(1.0)
    assert 1 / factors[(0, -1)] == pytest.approx(elliptical.head_to_back(wind))


def test_the_shape_uses_the_same_bearing_convention_as_the_main_model():
    """Both terms must peak on the same neighbour, for any wind direction."""
    for toward in (0, 45, 135, 200, 315):
        ellipse = elliptical.step_factors(30.0, toward)
        cos_cubed = spread._step_propensity(30.0, toward)
        assert (max(range(8), key=ellipse.__getitem__)
                == max(range(8), key=cos_cubed.__getitem__))


def test_still_air_spreads_equally_in_every_direction():
    assert elliptical.step_factors(0.0, 0.0) == pytest.approx([1.0] * 8, abs=0.02)


def test_the_midflame_factor_is_what_keeps_the_ellipse_off_the_cap():
    """Without it a Santa Ana wind pins LB at the cap and the ellipse is a line.

    35 km/h is the Camp Fire's wind and 29 km/h the Palisades'; both have to
    land inside the usable range, not against the limit.
    """
    assert elliptical.length_to_breadth(35.0) < elliptical.LB_CAP
    unadjusted = 35.0 / elliptical.MIDFLAME_FACTOR
    assert elliptical.length_to_breadth(unadjusted) == elliptical.LB_CAP
