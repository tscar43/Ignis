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

import math
from datetime import datetime

from pyproj import Geod
from shapely.geometry import Polygon, shape
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


def _finite(value, label: str, problems: list[str]) -> bool:
    """A quantity has to be a real number before any comparison means anything.

    NaN fails every ordering silently: `nan < 0` is False, so a NaN wind speed
    walked straight through the range checks below and into the payload.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{label}: must be a number, got {value!r}")
        return False
    if not math.isfinite(value):
        problems.append(f"{label}: must be finite, got {value!r}")
        return False
    return True


def _coords(geometry: dict, label: str, problems: list[str]) -> None:
    """Every coordinate must be [lon, lat], finite, in range, in that order."""
    def walk(node):
        # Structure first. An empty ring, a scalar where a list belongs or a
        # one-element position used to raise IndexError/TypeError out of a
        # validator whose whole job is to return problems instead of raising.
        if not isinstance(node, (list, tuple)) or not node:
            problems.append(f"{label}: malformed coordinates {node!r}")
            return
        if isinstance(node[0], (int, float)):
            if len(node) < 2:
                problems.append(f"{label}: position needs [lon, lat], got {node!r}")
                return
            lon, lat = node[0], node[1]
            if not (_finite(lon, f"{label}: longitude", problems)
                    and _finite(lat, f"{label}: latitude", problems)):
                return
            if not -180 <= lon <= 180:
                problems.append(f"{label}: longitude {lon} out of range")
            if not -90 <= lat <= 90:
                problems.append(
                    f"{label}: latitude {lat} out of range -- coordinates are "
                    "[lon, lat], not [lat, lon]")
            return
        for part in node:
            walk(part)

    if not isinstance(geometry, dict) or "coordinates" not in geometry:
        problems.append(f"{label}: geometry has no coordinates")
        return
    walk(geometry["coordinates"])


def _is_number(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _features(collection, label: str, problems: list[str]) -> list:
    """`features` as a list of dict features, reporting rather than raising."""
    features = collection.get("features", [])
    if not isinstance(features, list):
        problems.append(f"{label}: features must be a list, got {features!r}")
        return []
    ok = [f for f in features if isinstance(f, dict)]
    if len(ok) != len(features):
        problems.append(f"{label}: every feature must be an object")
    return ok


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
    if not isinstance(points, dict) or points.get("type") != "FeatureCollection":
        problems.append("fire_points: must be a FeatureCollection")
        points = {}
    for index, feature in enumerate(_features(points, "fire_points", problems)):
        where = f"fire_points[{index}]"
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            problems.append(f"{where}: must be a Point")
            continue
        _coords(geometry, where, problems)
        for field in ("confidence", "frp", "acq_time"):
            if field not in (feature.get("properties") or {}):
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
        for index, feature in enumerate(_features(collection,
                                                  f"risk_polygons.{name}", problems)):
            where = f"risk_polygons.{name}[{index}]"
            geometry = feature.get("geometry")
            if (not isinstance(geometry, dict)
                    or geometry.get("type") not in ("Polygon", "MultiPolygon")):
                problems.append(f"{where}: must be a Polygon or MultiPolygon")
                continue
            before = len(problems)
            _coords(geometry, where, problems)
            if len(problems) > before:
                continue  # shape() on bad coordinates raises rather than reports
            geometry = shape(geometry)
            if not geometry.is_valid:
                problems.append(f"{where}: invalid geometry (self-intersection?)")
            pieces.append(geometry)
        # An empty band is an EMPTY GEOMETRY, never None. As None it used to
        # mean "skip every check that mentions this band", so blanking h6 while
        # h3 stayed full -- and while summary.area_km2.h6 still claimed the old
        # area -- produced no problems at all.
        bands[name] = unary_union(pieces) if pieces else Polygon()

    # The rule Backend's scoring depends on: h6 contains h3 contains h1
    # contains current. An empty outer band under a non-empty inner one is
    # exactly the case this has to catch, so emptiness is not an exemption.
    for inner, outer in zip(BANDS, BANDS[1:]):
        if bands.get(inner) is None or bands.get(outer) is None:
            continue  # band absent or malformed; already reported above
        if bands[outer].is_empty and not bands[inner].is_empty:
            problems.append(
                f"risk_polygons: {outer} is empty but {inner} is not; "
                "bands are cumulative, so an outer band cannot be smaller")
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
    if "wind_toward_deg" in summary and _finite(
            summary["wind_toward_deg"], "summary.wind_toward_deg", problems):
        if not 0 <= summary["wind_toward_deg"] < 360:
            problems.append(f"summary.wind_toward_deg: {summary['wind_toward_deg']} "
                            "outside [0, 360); it is a bearing fire spreads TOWARD")
    if "wind_speed_kmh" in summary and _finite(
            summary["wind_speed_kmh"], "summary.wind_speed_kmh", problems):
        if summary["wind_speed_kmh"] < 0:
            problems.append("summary.wind_speed_kmh: negative")

    areas = summary.get("area_km2")
    if not isinstance(areas, dict):
        problems.append(f"summary.area_km2: must be an object, got {areas!r}")
        areas = {}
    for name in BANDS:
        if name not in areas:
            problems.append(f"summary.area_km2: missing {name!r}")
        else:
            _finite(areas[name], f"summary.area_km2.{name}", problems)
    reported = [areas[n] for n in BANDS if n in areas and _is_number(areas[n])]
    if reported != sorted(reported):
        problems.append(f"summary.area_km2: must not decrease across bands, got {reported}")
    for name in BANDS:
        if (name not in areas or bands.get(name) is None
                or not _is_number(areas[name])):
            continue  # missing or non-finite; already reported
        # An empty band measures 0. _geodesic_km2 is only meaningful on a
        # polygon, and this is the check that catches a blanked h6 still
        # reporting the area it had when it was full.
        actual = 0.0 if bands[name].is_empty else _geodesic_km2(bands[name])
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
