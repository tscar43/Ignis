"""Machine-checkable version of the risk payload contract.

The contract currently lives in prose (demo_data/README.md) and in whatever
each of us remembers, which is how three people drift apart in an afternoon.
This checks a payload against it and returns the problems.

Deliberately not jsonschema: the two rules that actually matter -- lon/lat
order and cumulative nesting -- are geometric, and no JSON schema expresses
either. A plain function covers the structural rules too and adds no
dependency.

`contracts/` is shared, so this lives here until the team agrees to move it.
Run `python -m backend.fire.contract --propose` to print the version to put
there.
"""

from __future__ import annotations

from datetime import datetime

from pyproj import Geod
from shapely.geometry import shape
from shapely.ops import unary_union

BANDS = ("current", "h1", "h3", "h6")
TOP_LEVEL = ("generated_at", "data_as_of", "fire_points", "risk_polygons", "summary")
SUMMARY_KEYS = ("wind_speed_kmh", "wind_toward_deg", "primary_spread_direction",
                "dominant_fuels", "area_km2")

# Rounding coordinates for file size perturbs the bands by a hair, so nesting
# is checked by leaked area rather than a strict covers(). Well under a square
# metre at this latitude.
NESTING_TOLERANCE_DEG2 = 1e-12
AREA_TOLERANCE = 0.10  # summary.area_km2 vs the polygons themselves

_GEOD = Geod(ellps="WGS84")


def _timestamp(value, label: str, problems: list[str]) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        problems.append(f"{label}: must be ISO8601 UTC ending in Z, got {value!r}")
        return
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        problems.append(f"{label}: unparseable timestamp {value!r}")


def _coords(geometry: dict, label: str, problems: list[str]) -> None:
    """Every coordinate must be [lon, lat], in range, in that order."""
    def walk(node):
        if isinstance(node[0], (int, float)):
            lon, lat = node[0], node[1]
            if not -180 <= lon <= 180:
                problems.append(f"{label}: longitude {lon} out of range")
            if not -90 <= lat <= 90:
                problems.append(
                    f"{label}: latitude {lat} out of range -- coordinates are "
                    "[lon, lat], not [lat, lon]")
            return
        for part in node:
            walk(part)

    walk(geometry["coordinates"])


def _geodesic_km2(geometry) -> float:
    return abs(_GEOD.geometry_area_perimeter(geometry)[0]) / 1e6


def validate(payload: dict) -> list[str]:
    """Problems with `payload`. Empty list means it satisfies the contract."""
    problems: list[str] = []

    for key in TOP_LEVEL:
        if key not in payload:
            problems.append(f"missing top-level key {key!r}")
    if problems:
        return problems  # nothing else will make sense

    _timestamp(payload["generated_at"], "generated_at", problems)
    for source in ("firms", "weather"):
        if source not in payload["data_as_of"]:
            problems.append(f"data_as_of: missing {source!r}")
        else:
            _timestamp(payload["data_as_of"][source], f"data_as_of.{source}", problems)

    points = payload["fire_points"]
    if points.get("type") != "FeatureCollection":
        problems.append("fire_points: must be a FeatureCollection")
    for index, feature in enumerate(points.get("features", [])):
        where = f"fire_points[{index}]"
        if feature["geometry"]["type"] != "Point":
            problems.append(f"{where}: must be a Point")
        _coords(feature["geometry"], where, problems)
        for field in ("confidence", "frp", "acq_time"):
            if field not in feature.get("properties", {}):
                problems.append(f"{where}: properties missing {field!r}")

    bands = {}
    for name in BANDS:
        if name not in payload["risk_polygons"]:
            problems.append(f"risk_polygons: missing band {name!r}")
            continue
        collection = payload["risk_polygons"][name]
        if collection.get("type") != "FeatureCollection":
            problems.append(f"risk_polygons.{name}: must be a FeatureCollection")
            continue
        pieces = []
        for index, feature in enumerate(collection.get("features", [])):
            where = f"risk_polygons.{name}[{index}]"
            if feature["geometry"]["type"] not in ("Polygon", "MultiPolygon"):
                problems.append(f"{where}: must be a Polygon or MultiPolygon")
                continue
            _coords(feature["geometry"], where, problems)
            geometry = shape(feature["geometry"])
            if not geometry.is_valid:
                problems.append(f"{where}: invalid geometry (self-intersection?)")
            pieces.append(geometry)
        bands[name] = unary_union(pieces) if pieces else None

    # The rule Backend's scoring depends on: h6 contains h3 contains h1
    # contains current.
    for inner, outer in zip(BANDS, BANDS[1:]):
        if bands.get(inner) is None or bands.get(outer) is None:
            continue
        leaked = bands[inner].difference(bands[outer]).area
        if leaked > NESTING_TOLERANCE_DEG2:
            problems.append(
                f"risk_polygons: {outer} must contain {inner} "
                f"(leaked {leaked:.3g} deg2); bands are cumulative, not rings")

    summary = payload["summary"]
    for key in SUMMARY_KEYS:
        if key not in summary:
            problems.append(f"summary: missing {key!r}")
    if "wind_toward_deg" in summary and not 0 <= summary["wind_toward_deg"] < 360:
        problems.append(f"summary.wind_toward_deg: {summary['wind_toward_deg']} "
                        "outside [0, 360); it is a bearing fire spreads TOWARD")
    if "wind_speed_kmh" in summary and summary["wind_speed_kmh"] < 0:
        problems.append("summary.wind_speed_kmh: negative")

    areas = summary.get("area_km2", {})
    for name in BANDS:
        if name not in areas:
            problems.append(f"summary.area_km2: missing {name!r}")
    reported = [areas[n] for n in BANDS if n in areas]
    if reported != sorted(reported):
        problems.append(f"summary.area_km2: must not decrease across bands, got {reported}")
    for name in BANDS:
        if name not in areas or bands.get(name) is None:
            continue
        actual = _geodesic_km2(bands[name])
        if abs(actual - areas[name]) > max(AREA_TOLERANCE * actual, 0.5):
            problems.append(
                f"summary.area_km2.{name}: reports {areas[name]} but the "
                f"polygons measure {actual:.1f} km2")

    return problems


def check(payload: dict) -> dict:
    """Raise on a contract violation, otherwise hand the payload straight back."""
    problems = validate(payload)
    if problems:
        raise ValueError("payload violates the contract:\n  - "
                         + "\n  - ".join(problems))
    return payload


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    demo = Path(__file__).resolve().parents[2] / "demo_data"
    targets: list[tuple[str, dict]] = []
    for path in sorted(demo.glob("risk_*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        frames = loaded if isinstance(loaded, list) else [loaded]
        targets += [(f"{path.name}[{i}]" if len(frames) > 1 else path.name, frame)
                    for i, frame in enumerate(frames)]

    if "--live" in sys.argv:
        from .spread import risk_payload
        targets.append(("risk_payload() live", risk_payload()))

    failed = 0
    for label, payload in targets:
        problems = validate(payload)
        failed += bool(problems)
        print(f"{'FAIL' if problems else 'ok  '}  {label}")
        for problem in problems:
            print(f"        {problem}")
    print(f"\n{len(targets) - failed}/{len(targets)} payloads satisfy the contract")
    sys.exit(1 if failed else 0)
