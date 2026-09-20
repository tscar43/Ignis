"""Fire spread as a shortest-path problem: how soon can fire reach each cell.

Dijkstra over the grid, not a stepped cellular automaton. Deterministic, one
pass for all four bands, and the bands nest by construction -- arrival <= 60
is a subset of arrival <= 180 -- which is exactly what the contract promises.

Everything here is EPSG:5070 metres. Reprojection to EPSG:4326 happens once,
in bands_to_geojson, at the very end.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush

import numpy as np
import rasterio.features
from affine import Affine
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from ..weather import nws
from . import contract, firms, goes, landfire, terrain
from .firms import DEMO_BBOX

BANDS = {"current": 0, "h1": 60, "h3": 180, "h6": 360}  # minutes

# 8-neighbourhood: (drow, dcol). Compass bearing of each step is derived from
# it, so the wind term and the step length stay in sync.
NEIGHBOURS = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]

# S = base + k_wind * wind_kmh * ((1 + cos theta) / 2) ** exponent
# base is nonzero so fire still creeps upwind and along the flanks.
#
# The exponent is the shape knob. The brief's linear form gives a head:flank
# ratio of 1.8, which spreads a near-circular blob; real wind-driven fires run
# 4:1 to 10:1. Cubing gets 5:1 without implementing a full elliptical model.
BASE = 0.10
K_WIND = 0.03
WIND_EXPONENT = 3.0

# Base spread rate, the single calibration knob. Fitted against the replay
# fire: seeding from the 19:50Z pass, the observed detection footprint grew
# 90 -> ~188 km2 over the next 6 h, and R0=10 with the fuel term reproduces
# that to within 5%. Wind-only overshoots by ~40%, which is the point of the
# baseline comparison.
#
# Caveat for the pitch: this window is *after* the Camp Fire's fast run, so
# R0 is fitted to a fire that had already slowed. A live fire in its first
# hours will move faster than this. Re-fit per incident.
R0_M_PER_MIN = 10.0


def _step_propensity(wind_kmh: float, wind_toward_deg: float) -> list[float]:
    """Wind factor per neighbour direction. Position-independent, so 8 numbers.

    Row index grows southward, so north is -drow. The bearing of a step is
    atan2(east, north) in compass degrees.
    """
    factors = []
    for drow, dcol in NEIGHBOURS:
        bearing = math.degrees(math.atan2(dcol, -drow)) % 360
        theta = math.radians(bearing - wind_toward_deg)
        factors.append(BASE + K_WIND * wind_kmh * ((1 + math.cos(theta)) / 2) ** WIND_EXPONENT)
    return factors


def arrival_times(
    ignition: np.ndarray,
    wind_kmh: float,
    wind_toward_deg: float,
    cell_m: float,
    propensity: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    horizon_min: float = max(BANDS.values()),
    r0: float = R0_M_PER_MIN,
    step_factors: list[float] | None = None,
) -> np.ndarray:
    """Minutes until fire reaches each cell. Unreached cells come back inf.

    `propensity` is the per-cell F_fuel; None means no fuel term. A cell with
    propensity 0 is a hard barrier and is never entered. `slope` is F_slope as
    (len(NEIGHBOURS), rows, cols) -- directional, so it cannot fold into
    `propensity`. Both None gives the wind-only baseline.

    `step_factors` replaces this module's wind shape with one supplied per
    NEIGHBOURS direction, which is how `elliptical.py` runs the FARSITE-class
    baseline through the same solver. None keeps the cos^3 form.
    """
    if propensity is None:
        propensity = np.ones(ignition.shape, dtype="float32")
    rows, cols = ignition.shape
    wind = (_step_propensity(wind_kmh, wind_toward_deg)
            if step_factors is None else step_factors)
    lengths = [cell_m * math.hypot(dr, dc) for dr, dc in NEIGHBOURS]

    arrival = np.full(ignition.shape, np.inf, dtype="float64")
    arrival[ignition] = 0.0
    queue = [(0.0, int(r), int(c)) for r, c in zip(*np.nonzero(ignition))]
    queue.sort()

    while queue:
        time, row, col = heappop(queue)
        if time > arrival[row, col]:
            continue  # stale entry, already relaxed by a cheaper path
        for index, ((drow, dcol), length, wind_factor) in enumerate(
                zip(NEIGHBOURS, lengths, wind)):
            r, c = row + drow, col + dcol
            if not (0 <= r < rows and 0 <= c < cols):
                continue
            rate = r0 * wind_factor * propensity[r, c]
            if slope is not None:
                rate *= slope[index, r, c]
            if rate <= 0:
                continue  # non-burnable: fire does not enter this cell
            candidate = time + length / rate
            if candidate < arrival[r, c] and candidate <= horizon_min:
                arrival[r, c] = candidate
                heappush(queue, (candidate, r, c))
    return arrival


def seed_from_hotspots(hotspots, transform, shape_):
    """Ignition mask from satellite detections.

    A detection is a pixel, not a point, so mark every cell within half a pixel
    of it rather than the single cell it lands in. The size is per hotspot:
    VIIRS is 375 m, a GOES ABI cell is kilometres, and a seed that ignores the
    difference either loses the ABI detection entirely or inflates the VIIRS
    footprint to match it.
    """
    to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    xs, ys = to_albers.transform([h.lon for h in hotspots], [h.lat for h in hotspots])
    cols = ((np.array(xs) - transform.c) / transform.a).astype(int)
    rows = ((np.array(ys) - transform.f) / transform.e).astype(int)

    mask = np.zeros(shape_, dtype=bool)
    for row, col, hotspot in zip(rows, cols, hotspots):
        reach = max(1, int(round(hotspot.pixel_m / 2 / abs(transform.a))))
        if 0 <= row < shape_[0] and 0 <= col < shape_[1]:
            mask[max(0, row - reach):row + reach + 1,
                 max(0, col - reach):col + reach + 1] = True
    return mask


def bands_to_geojson(arrival: np.ndarray, transform, simplify_m: float = 60.0,
                     close_m: float = 150.0, ndigits: int = 6) -> dict:
    """The contract's `risk_polygons`, cumulative and in EPSG:4326.

    `close_m` is a morphological closing. Seeding from satellite pixels leaves
    a lattice of pinholes between detections, which polygonizes into a hundred
    ragged rings the frontend then has to draw. Closing merges them.

    Coordinates are snapped to `ndigits` (~0.1 m) before the final union, not
    after: snapping a union's intersection vertices moves them off the inner
    band's edge and breaks the nesting Backend's scoring assumes.
    """
    to_wgs = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True).transform

    # Pass 1: polygonize in metres, cumulative.
    projected, previous, areas = {}, None, {}
    for name, minutes in BANDS.items():
        mask = arrival <= minutes
        pieces = [shape(geom) for geom, value in rasterio.features.shapes(
            mask.astype("uint8"), mask=mask, transform=transform) if value == 1]
        geom = (unary_union(pieces).buffer(close_m).buffer(-close_m)
                .simplify(simplify_m).buffer(0)) if pieces else previous
        if geom is not None and previous is not None:
            geom = unary_union([geom, previous])  # simplify() can bite into the inner band
        previous = geom
        projected[name] = geom
        areas[name] = round(geom.area / 1e6, 1) if geom else 0.0

    # Pass 2: reproject, snap, then re-union so nesting survives the rounding.
    out, previous = {}, None
    for name in BANDS:
        geom = projected[name]
        if geom is None or geom.is_empty:
            out[name] = {"type": "FeatureCollection", "features": []}
            continue
        geom = shape(_round_coords(mapping(shapely_transform(to_wgs, geom)), ndigits))
        if previous is not None:
            geom = unary_union([geom, previous])
        previous = geom
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        out[name] = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": mapping(part),
             "properties": {"band": name}} for part in parts]}

    return {"risk_polygons": out, "area_km2": areas}


def _round_coords(geojson: dict, ndigits: int) -> dict:
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            return [round(v, ndigits) for v in coords]
        return [walk(part) for part in coords]

    geojson["coordinates"] = walk(geojson["coordinates"])
    return geojson


@dataclass(frozen=True)
class Scene:
    """Observations and layers for one moment, fetched once.

    Split out of risk_payload so an ensemble can run several models against
    the same seed, wind and rasters instead of refetching per model.
    """

    ignition: np.ndarray
    codes: np.ndarray
    propensity: np.ndarray
    slope: np.ndarray
    transform: Affine
    wind: nws.Wind
    seed: list
    seed_time: datetime

    @property
    def cell_m(self) -> float:
        return self.transform.a


def gather(bbox=DEMO_BBOX, when: datetime | None = None,
           peak_window_h: int = 8) -> Scene:
    """Everything a spread model needs for `bbox` at `when` (None = live).

    Both derived layers are always built -- the rasters are disk-cached, and a
    model that wants the wind-only baseline just passes None to arrival_times.
    """
    live_mode = when is None
    hotspots = firms.fetch_many(
        firms.LIVE_SOURCES if live_mode else firms.ARCHIVE_SOURCES, bbox=bbox,
        # Replay starts a day early: at 01:50 the newest pass is still
        # yesterday evening's, and fetching only `when`'s date would miss it.
        start_date=None if live_mode else when.date() - timedelta(days=1),
        days=1 if live_mode else 2)

    # Seed from one satellite pass, not all of them: older detections are
    # already-burned area, and seeding them projects the fire twice. Replay
    # uses the newest pass *at or before* `when`, which is all a live system
    # would have known at that moment -- often hours stale, which is the point.
    available = [h.acq_time for h in hotspots
                 if live_mode or h.acq_time <= when]
    if not available:
        raise RuntimeError(f"no hotspots in {bbox} at {when or 'the latest pass'}")
    seed_time = max(available)
    seed = [h for h in hotspots if h.acq_time == seed_time]

    # Live only: add the newest GOES ABI frame, scanned minutes ago rather than
    # hours. Union rather than replace -- ABI sees only the hottest cores, so
    # alone it would shrink the footprint, while VIIRS alone freezes it at the
    # last overpass.
    #
    # This does not reopen the "seed from one pass" trap. That one was about
    # projecting a whole day of VIIRS passes, which re-runs the same growth
    # from the origin. Arrival time is a minimum over paths, so a seed inside
    # the envelope contributes nothing; only the outer edge moves, and the ABI
    # frame is the one observation entitled to move it.
    if live_mode:
        fresh = goes.fetch(bbox)
        if fresh:
            seed = seed + fresh
            seed_time = max(seed_time, fresh[0].acq_time)

    lat = (bbox[1] + bbox[3]) / 2
    lon = (bbox[0] + bbox[2]) / 2
    wind = (nws.live(lat, lon) if live_mode
            else nws.archived(lat, lon, seed_time, peak_window_h=peak_window_h))

    codes, profile = landfire.fetch("fuel", bbox=bbox)
    return Scene(
        ignition=seed_from_hotspots(seed, profile["transform"], codes.shape),
        codes=codes,
        propensity=landfire.fuel_factor(codes),
        slope=terrain.slope_factors(landfire.fetch("slope", bbox=bbox)[0],
                                   landfire.fetch("aspect", bbox=bbox)[0],
                                   NEIGHBOURS),
        transform=profile["transform"], wind=wind, seed=seed, seed_time=seed_time)


def assemble(scene: Scene, bands: dict, arrival: np.ndarray) -> dict:
    """The contract payload around an already-polygonized set of bands."""
    burned = scene.codes[np.isfinite(arrival)]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_as_of": {"firms": firms.iso(scene.seed_time),
                       "weather": scene.wind.observed_at},
        "fire_points": firms.to_feature_collection(scene.seed),
        "risk_polygons": bands["risk_polygons"],
        "summary": {
            "wind_speed_kmh": scene.wind.speed_kmh,
            "wind_toward_deg": round(scene.wind.toward_deg),
            "primary_spread_direction": scene.wind.compass,
            "dominant_fuels": landfire.dominant_fuels(burned),
            "area_km2": bands["area_km2"],
        },
    }


def risk_payload(bbox=DEMO_BBOX, when: datetime | None = None,
                 use_fuel: bool = True, use_slope: bool = True,
                 peak_window_h: int = 8) -> dict:
    """The whole contract, in one call. This is what the endpoint returns.

    `when=None` is live: NRT hotspots and current NWS wind. A datetime is
    replay: the SP archive and reanalysis wind for that hour.
    """
    scene = gather(bbox=bbox, when=when, peak_window_h=peak_window_h)
    arrival = arrival_times(
        scene.ignition, scene.wind.speed_kmh, scene.wind.toward_deg,
        cell_m=scene.cell_m,
        propensity=scene.propensity if use_fuel else None,
        slope=scene.slope if use_slope else None)
    # Fail here rather than shipping bad polygons to an evacuation UI. The
    # guard is on this path only, not in assemble(), so it cannot break the
    # ensemble while that is still being written.
    return contract.check(
        assemble(scene, bands_to_geojson(arrival, scene.transform), arrival))


def replay(start: datetime, offsets_h=(0, 1, 3, 6), bbox=DEMO_BBOX, **kwargs) -> list[dict]:
    """One payload per offset, as the system would have answered at that hour.

    Each frame re-seeds from whatever pass was newest then, so the frames show
    observation staleness as well as fire growth.
    """
    frames = []
    for hours in offsets_h:
        at = start + timedelta(hours=hours)
        frame = risk_payload(bbox=bbox, when=at, **kwargs)
        frame["replay"] = {"offset_h": hours,
                           "at": at.strftime("%Y-%m-%dT%H:%M:%SZ")}
        frames.append(frame)
    return frames


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    start = datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)

    if "--replay" in sys.argv:
        out = Path(__file__).resolve().parents[2] / "demo_data" / "risk_replay.json"
        frames = replay(start)
        out.write_text(json.dumps(frames, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
        for frame in frames:
            print(f"  T+{frame['replay']['offset_h']}h  hotspots as of "
                  f"{frame['data_as_of']['firms']}  "
                  f"h6 {frame['summary']['area_km2']['h6']} km2")
        sys.exit()

    payload = risk_payload(when=None if "--live" in sys.argv else start)
    print(json.dumps(payload["summary"], indent=2))
    print("data_as_of:", payload["data_as_of"])
    print("seed detections:", len(payload["fire_points"]["features"]))
    for name, fc in payload["risk_polygons"].items():
        print(f"  {name}: {len(fc['features'])} polygons")
