"""Offline tests for the arrival-time spread. No network.

These guard the two things Backend's routing depends on: wind pushes the fire
the way the contract says it does, and the bands nest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import spread  # noqa: E402

CELL = 100.0


def _single_seed(size=41):
    ignition = np.zeros((size, size), dtype=bool)
    ignition[size // 2, size // 2] = True
    return ignition


def test_fire_runs_downwind_not_upwind():
    """wind_toward=90 is due east, so east must be reached before west."""
    ignition = _single_seed()
    arrival = spread.arrival_times(ignition, wind_kmh=40, wind_toward_deg=90,
                                   cell_m=CELL)
    mid = ignition.shape[0] // 2
    east, west = arrival[mid, mid + 5], arrival[mid, mid - 5]
    assert east < west, f"east {east} should beat west {west}"
    assert west / east > 3, "head should clearly outrun the back"


def test_every_compass_direction_maps_to_the_right_neighbour():
    """A wrong sign on drow flips north and south and nobody notices."""
    mid = 20
    for toward, (drow, dcol) in [(0, (-1, 0)), (90, (0, 1)),
                                 (180, (1, 0)), (270, (0, -1))]:
        arrival = spread.arrival_times(_single_seed(), wind_kmh=40,
                                       wind_toward_deg=toward, cell_m=CELL)
        downwind = arrival[mid + drow * 5, mid + dcol * 5]
        upwind = arrival[mid - drow * 5, mid - dcol * 5]
        assert downwind < upwind, f"toward={toward} spread the wrong way"


def test_zero_propensity_is_a_hard_barrier():
    ignition = _single_seed()
    propensity = np.ones(ignition.shape, dtype="float32")
    propensity[:, 25:] = 0.0  # wall across the path
    arrival = spread.arrival_times(ignition, wind_kmh=40, wind_toward_deg=90,
                                   cell_m=CELL, propensity=propensity)
    assert np.isinf(arrival[:, 25:]).all(), "fire entered a non-burnable cell"


def test_bands_nest_after_polygonizing():
    ignition = _single_seed()
    arrival = spread.arrival_times(ignition, wind_kmh=30, wind_toward_deg=240,
                                   cell_m=CELL)
    # north-up transform, origin at a plausible Albers coordinate
    transform = Affine(CELL, 0, -2_000_000, 0, -CELL, 2_000_000)
    result = spread.bands_to_geojson(arrival, transform)

    areas = result["area_km2"]
    assert areas["current"] <= areas["h1"] <= areas["h3"] <= areas["h6"]
    assert areas["h6"] > areas["current"], "nothing spread at all"

    from shapely.geometry import shape as to_shape
    from shapely.ops import unary_union

    bands = {name: unary_union([to_shape(f["geometry"]) for f in fc["features"]])
             for name, fc in result["risk_polygons"].items()}
    for inner, outer in [("current", "h1"), ("h1", "h3"), ("h3", "h6")]:
        leaked = bands[inner].difference(bands[outer]).area
        assert leaked < 1e-15, f"{outer} must contain {inner} (leaked {leaked:.3g})"


def test_output_is_lon_lat_degrees():
    arrival = spread.arrival_times(_single_seed(), wind_kmh=30,
                                   wind_toward_deg=240, cell_m=CELL)
    transform = Affine(CELL, 0, -2_000_000, 0, -CELL, 2_000_000)
    fc = spread.bands_to_geojson(arrival, transform)["risk_polygons"]["h6"]
    lon, lat = fc["features"][0]["geometry"]["coordinates"][0][0]
    assert -180 <= lon <= 180 and -90 <= lat <= 90
    assert lon < 0 < lat, "coordinates must be [lon, lat] in CONUS"


def test_iou_endpoints():
    from backend.fire.validate import iou

    a = np.zeros((4, 4), bool)
    a[:2] = True
    b = np.zeros((4, 4), bool)
    b[2:] = True
    assert iou(a, a) == 1.0
    assert iou(a, b) == 0.0
    assert iou(a, a | b) == 0.5
    assert iou(np.zeros((4, 4), bool), np.zeros((4, 4), bool)) == 0.0


# --------------------------------------------------- the grid is not a compass
def test_the_wind_bearing_is_rotated_into_the_grid_frame():
    """Step bearings are EPSG:5070 degrees; the weather feed reports true ones.

    Comparing them directly rotated every wind response by the meridian
    convergence -- about 15.7 degrees over Paradise.
    """
    plain = spread._step_propensity(40.0, 0.0)
    rotated = spread._step_propensity(40.0, 0.0, convergence_deg=-15.72)
    assert plain != rotated

    # A true-north wind under a -15.7 degree convergence runs up a grid
    # bearing of +15.7, which leans the head toward the north-east step.
    north = spread.NEIGHBOURS.index((-1, 0))
    northeast = spread.NEIGHBOURS.index((-1, 1))
    assert rotated[northeast] > plain[northeast]
    assert rotated[north] < plain[north]

    # Rotating the bearing by hand is the same as passing the convergence,
    # which is what makes this a change of frame rather than a fudge factor.
    # Grid north lies 15.72 degrees WEST of true north here, so a true-north
    # wind is 15.72 degrees EAST of grid north: the sign flips on the way in.
    assert spread._step_propensity(40.0, 15.72) == pytest.approx(rotated)


def test_arrival_times_forwards_the_convergence_to_the_wind_shape():
    """Accepted and ignored is the failure mode a default of 0 invites."""
    ignition = _single_seed(21)
    kwargs = dict(wind_kmh=40, wind_toward_deg=0.0, cell_m=CELL)
    straight = spread.arrival_times(ignition, **kwargs)
    rotated = spread.arrival_times(ignition, convergence_deg=-40.0, **kwargs)
    assert not np.allclose(straight[np.isfinite(straight)].sum(),
                           rotated[np.isfinite(rotated)].sum()) or \
        not np.array_equal(np.isfinite(straight), np.isfinite(rotated))


# --------------------------------------------- a bearing must stay below 360
def test_a_rounded_bearing_never_reaches_360(monkeypatch):
    """round(359.6) is 360, and the contract rejects 360 as a bearing.

    Valid wind, valid run, payload rejected at the very last step -- and
    `assemble` is shared, so MAGI had it too.
    """
    from datetime import datetime, timezone

    from backend.fire import firms, landfire
    from backend.weather import nws

    monkeypatch.setattr(landfire, "dominant_fuels", lambda codes, top=2: [])
    monkeypatch.setattr(firms, "to_feature_collection",
                        lambda seed: {"type": "FeatureCollection", "features": []})
    scene = spread.Scene(
        ignition=np.zeros((2, 2), bool), codes=np.zeros((2, 2), "int16"),
        propensity=np.ones((2, 2), "float32"),
        slope=np.ones((len(spread.NEIGHBOURS), 2, 2), "float32"),
        transform=Affine(120.0, 0, 0, 0, -120.0, 0),
        wind=nws.Wind(12.0, 359.6, "2026-09-20T00:00:00Z"), seed=[],
        seed_time=datetime(2026, 9, 20, tzinfo=timezone.utc))

    summary = spread.assemble(scene, {"risk_polygons": {}, "area_km2": {}},
                              np.full((2, 2), np.inf))["summary"]
    assert summary["wind_toward_deg"] == 0
    assert 0 <= summary["wind_toward_deg"] < 360


# ------------------------------------------------- one pass, not one minute
def _hotspot(hour, minute, lat=39.76):
    from datetime import datetime, timezone

    from backend.fire.firms import Hotspot

    return Hotspot(lon=-121.62, lat=lat, confidence="h", frp=10.0,
                   acq_time=datetime(2026, 9, 20, hour, minute, tzinfo=timezone.utc),
                   sensor="VIIRS", source="VIIRS_SNPP_SP")


def _stub_layers(monkeypatch, shape=(4, 4)):
    """Everything `gather` fetches, replaced. Returns the captured seed list."""
    from backend.fire import goes, landfire
    from backend.weather import nws

    transform = Affine(120.0, 0.0, -2_200_000.0, 0.0, -120.0, 2_000_000.0)
    captured = []

    def seed_from_hotspots(seed, _transform, shape_):
        captured[:] = list(seed)
        return np.zeros(shape_, dtype=bool)

    monkeypatch.setattr(landfire, "fetch",
                        lambda layer, bbox=None, **kw: (np.full(shape, 101, "int16"),
                                                        {"transform": transform}))
    monkeypatch.setattr(landfire, "fuel_factor",
                        lambda codes: np.ones(shape, "float32"))
    monkeypatch.setattr(spread.terrain, "slope_factors",
                        lambda *a, **kw: np.ones((len(spread.NEIGHBOURS), *shape),
                                                 "float32"))
    monkeypatch.setattr(spread.terrain, "grid_convergence", lambda *a, **kw: 0.0)
    monkeypatch.setattr(nws, "archived",
                        lambda *a, **kw: nws.Wind(10.0, 90.0, "2026-09-20T10:00:00Z"))
    monkeypatch.setattr(nws, "live",
                        lambda *a, **kw: nws.Wind(10.0, 90.0, "2026-09-20T10:00:00Z"))
    monkeypatch.setattr(spread, "seed_from_hotspots", seed_from_hotspots)
    monkeypatch.setattr(goes, "fetch", lambda bbox: [])
    return captured


def test_a_pass_spanning_several_minutes_is_seeded_whole(monkeypatch):
    """FIRMS stamps every detection with its own acquisition minute.

    One overpass of a bbox arrives as several adjacent minutes, so matching
    the newest minute exactly kept the last sliver of the pass and dropped the
    rest of it -- a seed a third of its true size, silently.
    """
    from datetime import datetime, timezone

    captured = _stub_layers(monkeypatch)
    this_pass = [_hotspot(10, 31), _hotspot(10, 32, lat=39.77),
                 _hotspot(10, 33, lat=39.78)]
    yesterday_evening = _hotspot(2, 33)

    spread.gather(when=datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
                  hotspots=this_pass + [yesterday_evening])
    assert len(captured) == 3
    assert yesterday_evening not in captured


def test_an_earlier_pass_is_still_excluded(monkeypatch):
    """The window groups one pass; it must not reach the previous overpass."""
    from datetime import datetime, timezone

    captured = _stub_layers(monkeypatch)
    spread.gather(when=datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
                  hotspots=[_hotspot(10, 33), _hotspot(9, 50)])
    assert len(captured) == 1


def test_a_goes_failure_degrades_to_viirs_instead_of_aborting(monkeypatch):
    """An unreachable S3 bucket must not take down a payload VIIRS supports."""
    from backend.fire import goes

    captured = _stub_layers(monkeypatch)

    def boom(bbox):
        raise RuntimeError("s3 unreachable")

    monkeypatch.setattr(goes, "fetch", boom)
    scene = spread.gather(when=None, hotspots=[_hotspot(10, 33)])
    assert len(captured) == 1
    assert scene.degraded == ("goes_unavailable",)


def test_goes_alone_can_seed_when_viirs_has_not_passed_over(monkeypatch):
    """Raising before GOES was tried threw away the one fresh observation."""
    from backend.fire import goes

    captured = _stub_layers(monkeypatch)
    abi = _hotspot(11, 55)
    monkeypatch.setattr(goes, "fetch", lambda bbox: [abi])
    scene = spread.gather(when=None, hotspots=[])
    assert captured == [abi]
    assert "no_viirs_pass" in scene.degraded


def test_no_observations_at_all_is_still_an_error(monkeypatch):
    from backend.fire import goes

    _stub_layers(monkeypatch)
    monkeypatch.setattr(goes, "fetch", lambda bbox: [])
    with pytest.raises(RuntimeError, match="no hotspots"):
        spread.gather(when=None, hotspots=[])
