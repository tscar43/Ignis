"""Fire spread as a shortest-path problem: how soon can fire reach each cell.

Dijkstra over the grid, not a stepped cellular automaton. Deterministic, one
pass for all four bands, and the bands nest by construction -- arrival <= 60
is a subset of arrival <= 180 -- which is exactly what the contract promises.

Everything here is EPSG:5070 metres. Reprojection to EPSG:4326 happens once,
in bands_to_geojson, at the very end.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from heapq import heappop, heappush

import numpy as np
import rasterio.features
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from ..weather import nws
from . import firms, landfire, terrain
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
) -> np.ndarray:
    """Minutes until fire reaches each cell. Unreached cells come back inf.

    `propensity` is the per-cell F_fuel; None means no fuel term. A cell with
    propensity 0 is a hard barrier and is never entered. `slope` is F_slope as
    (len(NEIGHBOURS), rows, cols) -- directional, so it cannot fold into
    `propensity`. Both None gives the wind-only baseline.
    """
    if propensity is None:
        propensity = np.ones(ignition.shape, dtype="float32")
    rows, cols = ignition.shape
    wind = _step_propensity(wind_kmh, wind_toward_deg)
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


def seed_from_hotspots(hotspots, transform, shape_, pixel_m: float = 375.0):
    """Ignition mask from FIRMS points.

    A detection is a ~375 m VIIRS pixel, not a point, so mark every cell within
    half a pixel of it rather than the single cell it lands in.
    """
    to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    xs, ys = to_albers.transform([h.lon for h in hotspots], [h.lat for h in hotspots])
    cols = ((np.array(xs) - transform.c) / transform.a).astype(int)
    rows = ((np.array(ys) - transform.f) / transform.e).astype(int)

    mask = np.zeros(shape_, dtype=bool)
    reach = max(1, int(round(pixel_m / 2 / abs(transform.a))))
    for row, col in zip(rows, cols):
        if 0 <= row < shape_[0] and 0 <= col < shape_[1]:
            mask[max(0, row - reach):row + reach + 1,
                 max(0, col - reach):col + reach + 1] = True
    return mask


def bands_to_geojson(arrival: np.ndarray, transform, simplify_m: float = 60.0,
                     close_m: float = 150.0) -> dict:
    """The contract's `risk_polygons`, cumulative and in EPSG:4326.

    `close_m` is a morphological closing. Seeding from satellite pixels leaves
    a lattice of pinholes between detections, which polygonizes into a hundred
    ragged rings the frontend then has to draw. Closing merges them.
    """
    to_wgs = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True).transform
    out, previous, areas = {}, None, {}

    for name, minutes in BANDS.items():
        mask = arrival <= minutes
        pieces = [shape(geom) for geom, value in rasterio.features.shapes(
            mask.astype("uint8"), mask=mask, transform=transform) if value == 1]
        geom = (unary_union(pieces).buffer(close_m).buffer(-close_m)
                .simplify(simplify_m).buffer(0)) if pieces else None

        if geom is not None and previous is not None:
            geom = unary_union([geom, previous])  # simplify() can bite into the inner band
        elif geom is None:
            geom = previous
        previous = geom
        areas[name] = round(geom.area / 1e6, 1) if geom else 0.0
        out[name] = _feature_collection(geom, to_wgs, name)

    return {"risk_polygons": out, "area_km2": areas}


def _feature_collection(geom, to_wgs, name: str) -> dict:
    if geom is None or geom.is_empty:
        return {"type": "FeatureCollection", "features": []}
    wgs = shapely_transform(to_wgs, geom)
    parts = list(wgs.geoms) if wgs.geom_type == "MultiPolygon" else [wgs]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": mapping(p), "properties": {"band": name}}
        for p in parts]}


def risk_payload(bbox=DEMO_BBOX, when: datetime | None = None,
                 use_fuel: bool = True, use_slope: bool = True,
                 peak_window_h: int = 8) -> dict:
    """The whole contract, in one call. This is what the endpoint returns.

    `when=None` is live: NRT hotspots and current NWS wind. A datetime is
    replay: the SP archive and reanalysis wind for that hour.
    """
    live_mode = when is None
    hotspots = firms.fetch_many(
        firms.LIVE_SOURCES if live_mode else firms.ARCHIVE_SOURCES,
        bbox=bbox, start_date=None if live_mode else when.date(), days=1)
    if not hotspots:
        raise RuntimeError(f"no hotspots in {bbox} for {when or 'the latest pass'}")

    # Seed from one satellite pass, not all of them: older detections are
    # already-burned area, and seeding them projects the fire twice.
    seed_time = max(h.acq_time for h in hotspots) if live_mode else min(
        (h.acq_time for h in hotspots if h.acq_time >= when), default=None)
    seed = [h for h in hotspots if h.acq_time == seed_time]

    lat = (bbox[1] + bbox[3]) / 2
    lon = (bbox[0] + bbox[2]) / 2
    wind = (nws.live(lat, lon) if live_mode
            else nws.archived(lat, lon, seed_time, peak_window_h=peak_window_h))

    codes, profile = landfire.fetch("fuel", bbox=bbox)
    propensity = landfire.fuel_factor(codes) if use_fuel else None
    slope = None
    if use_slope:
        slope = terrain.slope_factors(landfire.fetch("slope", bbox=bbox)[0],
                                      landfire.fetch("aspect", bbox=bbox)[0],
                                      NEIGHBOURS)
    ignition = seed_from_hotspots(seed, profile["transform"], codes.shape)
    arrival = arrival_times(ignition, wind.speed_kmh, wind.toward_deg,
                            cell_m=profile["transform"].a, propensity=propensity,
                            slope=slope)
    bands = bands_to_geojson(arrival, profile["transform"])

    burned = codes[np.isfinite(arrival)]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_as_of": {"firms": firms.iso(seed_time), "weather": wind.observed_at},
        "fire_points": firms.to_feature_collection(seed),
        "risk_polygons": bands["risk_polygons"],
        "summary": {
            "wind_speed_kmh": wind.speed_kmh,
            "wind_toward_deg": round(wind.toward_deg),
            "primary_spread_direction": wind.compass,
            "dominant_fuels": landfire.dominant_fuels(burned),
            "area_km2": bands["area_km2"],
        },
    }


if __name__ == "__main__":
    import json
    import sys

    replay = datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)
    payload = risk_payload(when=None if "--live" in sys.argv else replay)
    print(json.dumps(payload["summary"], indent=2))
    print("data_as_of:", payload["data_as_of"])
    print("seed detections:", len(payload["fire_points"]["features"]))
    for name, fc in payload["risk_polygons"].items():
        print(f"  {name}: {len(fc['features'])} polygons")
