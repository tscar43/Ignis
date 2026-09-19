"""Offline tests for the FBFM40 -> F_fuel lookup. No network."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import landfire  # noqa: E402


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
