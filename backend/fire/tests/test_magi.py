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

from backend.fire import magi, spread, validate  # noqa: E402
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
    """More wind and a faster R0 can only arrive sooner.

    Which is the point and also the limitation: Balthasar can never be the
    slowest of the three, so CONFIRMED is decided by Melchior and Casper alone.
    If this ever fails, that reasoning in the module docstring is stale too.
    """
    arrivals = magi.deliberate(_scene())
    assert (arrivals["BALTHASAR-2"] <= arrivals["MELCHIOR-1"] + 1e-9).all()


def test_no_magus_crosses_a_non_burnable_barrier():
    """Casper drops the fuel weighting but keeps the zeros.

    A model with no barriers at all puts the advisory fringe across a
    reservoir, which is the one part of the fuel layer nobody doubts.
    """
    propensity = np.ones((SIZE, SIZE), dtype="float32")
    propensity[:, 25:] = 0.0  # wall across the path
    scene = _scene(propensity)
    for name, arrival in magi.deliberate(scene).items():
        assert np.isinf(arrival[:, 25:]).all(), f"{name} entered a barrier"


def test_a_lone_dissenter_cannot_move_the_decision():
    """Timber that Casper refuses to slow down for is advisory, not consensus.

    F_fuel 0.2 is timber litter; Casper flattens it to 1.0 and so arrives about
    five times sooner. That disagreement must stay in the advisory band -- if it
    leaked into the majority the contract would ship one model's blind spot as
    consensus.
    """
    propensity = np.full((SIZE, SIZE), 0.2, dtype="float32")
    levels = magi.consensus(magi.deliberate(_scene(propensity)))
    edge = np.s_[:, -4:]  # far downwind, where only the fastest model reaches
    assert np.isfinite(levels["advisory"][edge]).any(), "nobody reached the edge"
    assert np.isinf(levels["majority"][edge]).all(), "dissent reached the decision"


def test_verdict_reads_the_six_hour_bands():
    line = magi._verdict({level: {"h6": area} for level, area in
                          [("advisory", 300.0), ("majority", 200.0),
                           ("confirmed", 100.0)]})
    assert "100.0 km2" in line and "200.0 km2" in line and "300.0 km2" in line


def test_drawn_rings_nest_across_levels():
    """The frontend draws three rings; a confirmed ring poking out of the
    majority one is a visible bug.

    bands_to_geojson only guarantees h1 subset h3 subset h6 *within* one call.
    Each level is polygonized separately, and the closing and simplify are what
    move edges, so nesting across levels needs its own check.
    """
    from shapely.geometry import shape as to_shape
    from shapely.ops import unary_union

    scene = _scene()
    levels = magi.consensus(magi.deliberate(scene))
    drawn = {}
    for level, arrival in levels.items():
        fc = spread.bands_to_geojson(arrival, scene.transform)["risk_polygons"]["h6"]
        drawn[level] = unary_union([to_shape(f["geometry"]) for f in fc["features"]])

    # Not exact: each level is closed and simplified on its own, so edges move
    # a few tens of metres either way. Measured leak is 1.5e-5 of the majority
    # ring, about 100 m2 -- invisible on the map, and not worth re-unioning the
    # polygons to remove. The tolerance is there to catch a real shredding.
    for inner, outer in [("confirmed", "majority"), ("majority", "advisory")]:
        leaked = drawn[inner].difference(drawn[outer]).area / drawn[outer].area
        assert leaked < 1e-4, f"{outer} must contain {inner} (leaked {leaked:.3g})"


def test_score_still_reaches_what_validate_exposes():
    """score() borrows validate's setup, including a private helper.

    That path needs the network, so nothing else covers it. This is the cheap
    guard: if validate's owner renames any of these, fail here rather than the
    first time someone runs --score.
    """
    assert hasattr(validate, "_setup"), "validate._setup gone -- magi.score is broken"
    assert callable(validate.iou)
    assert "camp" in validate.FIRES and len(validate.FIRES["camp"]) == 3
