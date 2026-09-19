"""Offline tests for the MAGI ensemble. No network.

Two things must hold: the confidence levels nest (the frontend draws them as
rings, and a hole in the middle is a bug), and a lone dissenter cannot move
the polygons that ship in the contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import magi, spread  # noqa: E402
from backend.weather.nws import Wind  # noqa: E402

CELL = 100.0
SIZE = 41


def _scene(propensity=None, toward_deg=90.0):
    ignition = np.zeros((SIZE, SIZE), dtype=bool)
    ignition[SIZE // 2, SIZE // 2] = True
    if propensity is None:
        propensity = np.ones((SIZE, SIZE), dtype="float32")
    return spread.Scene(
        ignition=ignition,
        codes=np.full((SIZE, SIZE), 101, dtype="int16"),
        propensity=propensity,
        slope=np.ones((len(spread.NEIGHBOURS), SIZE, SIZE), dtype="float32"),
        transform=Affine(CELL, 0, -2_000_000, 0, -CELL, 2_000_000),
        wind=Wind(speed_kmh=30.0, toward_deg=toward_deg,
                  observed_at="2018-11-08T19:00:00Z"),
        seed=[], seed_time=None)


def test_confidence_levels_nest_cellwise():
    levels = magi.consensus(magi.deliberate(_scene()))
    assert (levels["advisory"] <= levels["majority"]).all()
    assert (levels["majority"] <= levels["confirmed"]).all()


def test_protective_model_never_lags_the_calibrated_one():
    """Balthasar runs more wind and a faster R0, so it cannot arrive later."""
    arrivals = magi.deliberate(_scene())
    assert (arrivals["BALTHASAR-2"] <= arrivals["MELCHIOR-1"] + 1e-9).all()


def test_a_lone_dissenter_cannot_move_the_decision():
    """Casper ignores fuel, so only it crosses a non-burnable wall.

    That must show up as advisory-only. If it leaked into the majority the
    contract would be shipping one model's blind spot as consensus.
    """
    propensity = np.ones((SIZE, SIZE), dtype="float32")
    propensity[:, 25:] = 0.0
    levels = magi.consensus(magi.deliberate(_scene(propensity)))
    beyond = np.s_[:, 25:]
    assert np.isfinite(levels["advisory"][beyond]).any(), "Casper should cross"
    assert np.isinf(levels["majority"][beyond]).all(), "dissent reached the decision"
    assert np.isinf(levels["confirmed"][beyond]).all()


def test_verdict_reads_the_six_hour_bands():
    line = magi._verdict({level: {"h6": area} for level, area in
                          [("advisory", 300.0), ("majority", 200.0),
                           ("confirmed", 100.0)]})
    assert "100.0 km2" in line and "200.0 km2" in line and "300.0 km2" in line
