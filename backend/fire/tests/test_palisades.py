"""The exported Palisades replay fixture is well-formed. No network.

The tab built on this file is a validity claim, so the things worth pinning
are the ones that would let it lie quietly: a window whose prediction failed
to polygonize draws an empty map that still looks like a forecast, and an IoU
outside [0, 1] means the mask arithmetic went wrong upstream rather than that
the model did badly. Regenerate the fixture with:

    ./.venv/Scripts/python.exe -m backend.fire.palisades --json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire.palisades import REPLAY, WINDOWS  # noqa: E402

if not REPLAY.exists():
    pytest.skip(f"{REPLAY.name} not generated", allow_module_level=True)

REPLAYED = json.loads(REPLAY.read_text(encoding="utf-8"))


def coordinates(collection):
    return [feature["geometry"]["coordinates"] for feature in collection["features"]]


def test_every_window_is_exported():
    assert len(REPLAYED["windows"]) == len(WINDOWS)
    # Exactly one calibration window, and it is the first: presenting a fitted
    # IoU as a score is the one way this tab could mislead outright.
    assert [w["role"] for w in REPLAYED["windows"]][0] == "fit"
    assert [w["role"] for w in REPLAYED["windows"][1:]] == ["scored"] * (len(WINDOWS) - 1)


@pytest.mark.parametrize("index", range(len(WINDOWS)))
def test_window_has_drawable_geometry_and_sane_scores(index):
    window = REPLAYED["windows"][index]
    assert coordinates(window["seed"]) and coordinates(window["observed"])
    assert window["predictions"], "no model predictions in this window"
    for name, prediction in window["predictions"].items():
        assert coordinates(prediction), f"{name} polygonized to nothing"
    for name, stats in window["models"].items():
        for key in ("iou", "iou_growth"):
            assert 0.0 <= stats[key] <= 1.0, f"{name} {key} = {stats[key]}"
        assert stats["predicted_km2"] > 0


@pytest.mark.parametrize("index", range(len(WINDOWS)))
def test_coordinates_are_lon_lat_over_los_angeles(index):
    window = REPLAYED["windows"][index]
    for collection in [window["seed"], window["observed"],
                       *window["predictions"].values()]:
        for polygon in coordinates(collection):
            for lon, lat in polygon[0]:
                assert -119.5 < lon < -117.5, "coordinates look like [lat, lon]"
                assert 33.5 < lat < 34.7
