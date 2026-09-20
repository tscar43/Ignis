"""Offline tests for the FBFM40 -> F_fuel lookup. No network."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import landfire  # noqa: E402


def test_non_burnable_and_nodata_are_hard_barriers():
    # 91-99 is urban/water/ag/barren/snow; -9999 is the service's nodata.
    assert landfire.fuel_factor(np.array([91, 93, 98, 99, -9999, 0])).max() == 0


def test_fuel_groups_get_their_weights():
    codes = np.array([102, 122, 145, 165, 186, 203])
    expected = [1.0, 0.8, 0.7, 0.4, 0.2, 0.5]  # float32, so compare loosely
    assert landfire.fuel_factor(codes) == pytest.approx(expected)


def test_dominant_fuels_ignores_barriers_and_ranks_by_area():
    codes = np.array([91] * 50 + [165] * 20 + [102] * 10 + [186] * 5)
    assert landfire.dominant_fuels(codes) == ["timber understory", "grass"]


def test_vintage_follows_the_fire_not_a_constant():
    """A replay gets the last vintage published before its fire; live the newest.

    LF2016 was hardcoded with a comment saying to switch it for live, which is
    how a 2025 fire came to be modelled on 2016 vegetation. Nobody switches a
    constant per run.
    """
    from datetime import datetime, timezone

    assert landfire.vintage_for() == "LF2023"
    assert landfire.vintage_for(datetime(2018, 11, 8, tzinfo=timezone.utc)) == "LF2016"
    assert landfire.vintage_for(datetime(2021, 7, 15, tzinfo=timezone.utc)) == "LF2016"
    assert landfire.vintage_for(datetime(2025, 1, 8, tzinfo=timezone.utc)) == "LF2023"
    # Older than every vintage we carry: the oldest, not an empty max().
    assert landfire.vintage_for(datetime(1999, 1, 1, tzinfo=timezone.utc)) == "LF2016"


def test_the_cache_key_separates_vintages():
    """It did not, so re-pointing fuel at another vintage returned the old
    raster under the same tag -- and every cross-vintage experiment run that
    way measured one raster against itself."""
    import hashlib

    tags = set()
    for vintage in landfire.FUEL_SERVICES:
        service = landfire.service_for("fuel", vintage)
        tags.add(hashlib.sha1(f"{service}|bbox|size|5070".encode()).hexdigest()[:12])
    assert len(tags) == len(landfire.FUEL_SERVICES)
