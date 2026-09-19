"""Generate the FAKE contract payload in demo_data/ so Backend and Frontend are
never blocked on the real model.

Hand-drawn, deterministic, and shaped exactly like the real output will be:
EPSG:4326 lon/lat, cumulative h1/h3/h6 bands, a small `summary` the LLM reads.
Geometry is built in UTM 10N (meters) and only reprojected at export, same as
the real pipeline will do.

Run:  ./.venv/Scripts/python.exe backend/fire/make_demo_data.py
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform, unary_union

OUT = Path(__file__).resolve().parents[2] / "demo_data" / "risk_demo.json"

PROJ = "EPSG:32610"  # UTM zone 10N -- meters, covers the Butte County demo area
to_m = Transformer.from_crs("EPSG:4326", PROJ, always_xy=True).transform
to_wgs = Transformer.from_crs(PROJ, "EPSG:4326", always_xy=True).transform

# Frozen so the file regenerates byte-identical and teammates can diff it.
GENERATED_AT = "2026-09-19T14:00:00Z"
FIRMS_AS_OF = "2026-09-19T12:41:00Z"
WEATHER_AS_OF = "2026-09-19T13:00:00Z"

WIND_SPEED_KMH = 35
WIND_TOWARD_DEG = 240  # where the fire is pushed TO, not where wind comes from

# Fake VIIRS hotspots near Concow / Paradise, CA.
HOTSPOTS = [
    (-121.601, 39.762, "h", 42.1),
    (-121.618, 39.775, "n", 18.6),
    (-121.586, 39.751, "h", 65.4),
    (-121.630, 39.783, "l", 9.2),
]

# (downwind lobe length m, spread radius m) per band.
BANDS = {
    "current": (0, 640),
    "h1": (620, 610),
    "h3": (1750, 700),
    "h6": (3450, 830),
}

# Stand-ins for FBFM40 non-burnable cells (91-99): a reservoir and an irrigated
# ag strip. Subtracted from every band, so the bands bend around them the way
# the real model's hard barriers will.
BARRIERS_WGS = [
    [(-121.648, 39.742), (-121.631, 39.737), (-121.622, 39.722),
     (-121.640, 39.714), (-121.659, 39.723), (-121.661, 39.736)],
    [(-121.690, 39.790), (-121.664, 39.757), (-121.652, 39.762),
     (-121.678, 39.796)],
]


def wind_vector(toward_deg: float) -> tuple[float, float]:
    """Compass bearing -> unit vector in projected (easting, northing) meters."""
    rad = math.radians(toward_deg)
    return math.sin(rad), math.cos(rad)


def round_coords(geojson: dict, ndigits: int) -> dict:
    """Round every coordinate in a GeoJSON geometry, at any nesting depth."""
    def walk(c):
        if isinstance(c[0], (int, float)):
            return [round(v, ndigits) for v in c]
        return [walk(part) for part in c]

    geojson["coordinates"] = walk(geojson["coordinates"])
    return geojson


def band_geom(length_m: float, radius_m: float, rng: random.Random):
    """Teardrop per hotspot, elongated downwind, jittered so it isn't a blob."""
    ux, uy = wind_vector(WIND_TOWARD_DEG)
    lobes = []
    for lon, lat, _conf, frp in HOTSPOTS:
        x, y = to_m(lon, lat)
        # Hotter pixels (higher FRP) throw a slightly longer, wider lobe.
        heat = 0.75 + 0.5 * min(frp, 70.0) / 70.0
        for _ in range(3):  # a few offset lobes -> irregular union, not a capsule
            jitter_deg = rng.uniform(-22, 22)
            jx, jy = wind_vector(WIND_TOWARD_DEG + jitter_deg)
            ln = length_m * heat * rng.uniform(0.75, 1.15)
            r = radius_m * heat * rng.uniform(0.7, 1.05)
            tip = (x + jx * ln, y + jy * ln)
            axis = LineString([(x, y), tip]) if ln > 1 else Point(x, y)
            lobes.append(axis.buffer(r, quad_segs=8))
        # A little upwind/flanking creep, as the real F_wind base term allows.
        lobes.append(Point(x - ux * radius_m * 0.35, y - uy * radius_m * 0.35)
                     .buffer(radius_m * 0.45, quad_segs=8))
    return unary_union(lobes)


def main() -> None:
    rng = random.Random(1129)
    barriers = unary_union(
        [transform(to_m, shape({"type": "Polygon", "coordinates": [ring]}))
         for ring in BARRIERS_WGS]
    )

    polygons, areas, raw_prev, prev = {}, {}, None, None
    for name, (length_m, radius_m) in BANDS.items():
        geom = band_geom(length_m, radius_m, rng)
        if raw_prev is not None:
            geom = unary_union([geom, raw_prev])  # cumulative: h6 > h3 > h1 > current
        raw_prev = geom
        clipped = geom.difference(barriers).simplify(45).buffer(0)
        if prev is not None:
            # simplify() can shave a vertex inside the inner band; re-union to
            # keep the nesting the contract promises.
            clipped = unary_union([clipped, prev])
        prev = clipped
        polygons[name] = clipped
        areas[name] = round(clipped.area / 1e6, 1)

    # The contract teammates code against. Fail loudly here rather than in their
    # code. Checked by leaked area, not covers(): after a union GEOS's covers()
    # can still report False across a shared boundary by a float epsilon, so a
    # strict predicate would reject geometry nested to well under a millimeter.
    ordered = list(BANDS)
    for inner, outer in zip(ordered, ordered[1:]):
        leaked = polygons[inner].difference(polygons[outer]).area  # m2
        assert leaked < 1e-3, f"{outer} must contain {inner} (leaked {leaked:.3g} m2)"

    def fc(features: list) -> dict:
        return {"type": "FeatureCollection", "features": features}

    # Export: reproject, snap to ~0.1 m (keeps the file small), then re-union
    # cumulatively -- snapping alone can push an inner vertex a hair outside the
    # outer band, and Backend's scoring assumes h6 > h3 > h1 > current exactly.
    wgs, prev_wgs = {}, None
    for name in BANDS:
        geom = shape(round_coords(mapping(transform(to_wgs, polygons[name])), 6))
        if prev_wgs is not None:
            geom = unary_union([geom, prev_wgs])
        prev_wgs = geom
        wgs[name] = geom

    for inner, outer in zip(ordered, ordered[1:]):
        leaked = wgs[inner].difference(wgs[outer]).area  # deg2
        assert leaked < 1e-15, f"{outer} must contain {inner} in EPSG:4326 (leaked {leaked:.3g})"

    def band_fc(name: str) -> dict:
        geom = wgs[name]
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        return fc([
            {"type": "Feature",
             # Already snapped above; re-rounding here would move the union's
             # intersection vertices back off the inner band's edge.
             "geometry": mapping(part),
             "properties": {"band": name}}
            for part in parts
        ])

    payload = {
        "generated_at": GENERATED_AT,
        "data_as_of": {"firms": FIRMS_AS_OF, "weather": WEATHER_AS_OF},
        "fire_points": fc([
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [lon, lat]},
             "properties": {"confidence": conf, "frp": frp, "acq_time": FIRMS_AS_OF}}
            for lon, lat, conf, frp in HOTSPOTS
        ]),
        "risk_polygons": {name: band_fc(name) for name in BANDS},
        "summary": {
            "wind_speed_kmh": WIND_SPEED_KMH,
            "wind_toward_deg": WIND_TOWARD_DEG,
            "primary_spread_direction": "southwest",
            "dominant_fuels": ["shrub", "timber understory"],
            "area_km2": areas,
        },
    }

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    verts = sum(len(f["geometry"]["coordinates"][0])
                for b in payload["risk_polygons"].values() for f in b["features"])
    print(f"wrote {OUT}")
    print(f"areas km2: {areas}")
    print(f"{sum(len(b['features']) for b in payload['risk_polygons'].values())} "
          f"polygons, {verts} exterior vertices, {OUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
