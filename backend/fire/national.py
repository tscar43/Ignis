"""Every active wildfire in the country, not one hand-picked bbox.

`spread.risk_payload()` answers "what does this fire do next" for a bbox
somebody chose. This module chooses the boxes: one FIRMS query over CONUS,
cluster the detections into incidents, then run the same engine per incident.

Three things this deliberately does not do, all of them noted where they bite:
fires are ranked by radiative power and only the top `limit` are modelled, a
cluster wider than `MAX_SPAN_DEG` is clipped rather than run at a coarser
cell, and CONUS means CONUS -- Alaska and Hawaii need LANDFIRE's `_AK`/`_HI`
services, which `landfire.SERVICES` does not carry.

    $P -m backend.fire.national             # model the 12 largest, print a table
    $P -m backend.fire.national --list      # just discover, no modelling
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps

from . import firms, spread, wfigs
from .firms import Hotspot

# The FIRMS area API wants (west, south, east, north). This is the lower 48
# plus a coastal margin; it is also the footprint of the LANDFIRE CONUS
# services, so anything outside it has no fuel raster to model against.
CONUS = (-125.0, 24.4, -66.9, 49.4)

# Clustering: detections within a cell of each other, or in touching cells,
# are one fire. 0.05 deg is ~5.5 km of latitude -- wide enough to join the
# pixels of one incident across two sensors, tight enough to keep two fires
# in the same county apart.
EPS_DEG = 0.05
MIN_DETECTIONS = 2  # a lone pixel is more often an ag burn or a flare

PAD_DEG = 0.06  # room around the footprint for 6 h of spread
MAX_SPAN_DEG = 0.6

# Detections are clustered over `WINDOW_DAYS`, but persistence is judged over
# a longer `HISTORY_DAYS`, from the same single query. A wildfire does not burn
# the same 375 m cell for five straight days without an incident record; a
# landfill flare, a refinery and a steel mill do. Measured on one CONUS sweep:
# 60 clusters were persistent with no record, and their coordinates are the
# Houston ship channel, Port Arthur, the Soda Springs phosphate plant and
# Monterrey. Real fires are unaffected -- the Dome fire is persistent too, but
# it has a live WFIGS record.
WINDOW_DAYS = 2
HISTORY_DAYS = 5
PERSISTENT_DAYS = 4
CELL_DEG = 0.01  # the cell persistence is counted in, ~1 km

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Incident:
    """One clustered fire: its detections and the box the model runs over."""

    hotspots: tuple[Hotspot, ...]

    @property
    def frp_mw(self) -> float:
        return round(sum(h.frp for h in self.hotspots), 1)

    @property
    def lon(self) -> float:
        return round(sum(h.lon for h in self.hotspots) / len(self.hotspots), 4)

    @property
    def lat(self) -> float:
        return round(sum(h.lat for h in self.hotspots) / len(self.hotspots), 4)

    @property
    def id(self) -> str:
        """Stable-ish handle for a fire FIRMS gives no name to.

        Rounded to 0.01 deg (~1 km), so the id survives the footprint growing
        by a few pixels between passes but changes if the fire walks a km.
        Not an incident number: NIFC names are a separate feed.
        """
        ns = "N" if self.lat >= 0 else "S"
        ew = "E" if self.lon >= 0 else "W"
        return f"{abs(self.lat):05.2f}{ns}{abs(self.lon):06.2f}{ew}"

    @property
    def seed_time(self) -> datetime:
        return max(h.acq_time for h in self.hotspots)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Padded footprint, clipped to MAX_SPAN_DEG about the centroid.

        ponytail: a fire complex wider than MAX_SPAN_DEG gets modelled on its
        middle only -- the clip keeps one 2-degree cluster from turning into a
        10-million-cell Dijkstra and stalling the whole national run. Raising
        `cell_m` for big boxes is the real fix, once something needs it.
        """
        west = min(h.lon for h in self.hotspots) - PAD_DEG
        south = min(h.lat for h in self.hotspots) - PAD_DEG
        east = max(h.lon for h in self.hotspots) + PAD_DEG
        north = max(h.lat for h in self.hotspots) + PAD_DEG
        half = MAX_SPAN_DEG / 2
        if east - west > MAX_SPAN_DEG:
            west, east = self.lon - half, self.lon + half
        if north - south > MAX_SPAN_DEG:
            south, north = self.lat - half, self.lat + half
        return (round(west, 4), round(south, 4), round(east, 4), round(north, 4))

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "lon": self.lon,
            "lat": self.lat,
            "bbox": list(self.bbox),
            "detections": len(self.hotspots),
            "frp_mw": self.frp_mw,
            "newest_pass": firms.iso(self.seed_time),
        }


def cluster(hotspots, eps_deg: float = EPS_DEG,
            min_detections: int = MIN_DETECTIONS) -> list[Incident]:
    """Detections -> incidents, biggest radiative power first.

    Grid-snap plus a flood fill over touching cells: O(n) and stdlib-only,
    where DBSCAN would be a new dependency for the same answer at this scale.

    ponytail: the grid is in degrees, so a cell is ~5.5 km tall everywhere but
    3.6 km wide at 49N against 5.0 km at 25N. Fires cluster slightly more
    eagerly in the south. Project to metres if that ever matters.
    """
    cells: dict[tuple[int, int], list] = {}
    for hotspot in hotspots:
        key = (int(hotspot.lon // eps_deg), int(hotspot.lat // eps_deg))
        cells.setdefault(key, []).append(hotspot)

    incidents, seen = [], set()
    for start in cells:
        if start in seen:
            continue
        seen.add(start)
        stack, members = [start], []
        while stack:
            col, row = stack.pop()
            members.extend(cells[(col, row)])
            for dcol in (-1, 0, 1):
                for drow in (-1, 0, 1):
                    neighbour = (col + dcol, row + drow)
                    if neighbour in cells and neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
        if len(members) >= min_detections:
            incidents.append(Incident(tuple(members)))

    incidents.sort(key=lambda i: i.frp_mw, reverse=True)
    return incidents


def sweep(bbox=CONUS, **cluster_kwargs):
    """(incidents, persistent cells) from a single FIRMS query.

    Clusters come from the last `WINDOW_DAYS` so a fire's footprint is what it
    is now. The persistence count uses the whole `HISTORY_DAYS`, because the
    only way to tell a flare from a fire is that the flare was there yesterday,
    and the day before, at the same 1 km cell.
    """
    hotspots = firms.fetch_live(bbox, days=HISTORY_DAYS)
    if not hotspots:
        return [], set()

    seen: dict[tuple[float, float], set] = {}
    for spot in hotspots:
        cell = (round(spot.lon / CELL_DEG), round(spot.lat / CELL_DEG))
        seen.setdefault(cell, set()).add(spot.acq_time.date())
    persistent = {cell for cell, days in seen.items()
                  if len(days) >= PERSISTENT_DAYS}

    newest = max(spot.acq_time for spot in hotspots)
    window = timedelta(days=WINDOW_DAYS)
    recent = [spot for spot in hotspots if newest - spot.acq_time <= window]
    return cluster(recent, **cluster_kwargs), persistent


def discover(bbox=CONUS, **cluster_kwargs) -> list[Incident]:
    """Current incidents in `bbox`. Cheap: no rasters, no wind, no modelling."""
    return sweep(bbox, **cluster_kwargs)[0]


def is_static_source(incident: Incident, persistent: set) -> bool:
    """Has this cluster been burning in one spot for most of the week?"""
    return any((round(spot.lon / CELL_DEG), round(spot.lat / CELL_DEG)) in persistent
               for spot in incident.hotspots)


def currently_active(incidents, official: dict, persistent: set):
    """(kept, dropped) -- what is burning right now, and why the rest is not.

    Three ways to not be a current wildfire: the agency has it fully contained,
    nobody has touched its record in a week, or it is an industrial heat source
    that will be exactly as hot tomorrow. Everything else stays, including
    fresh heat nobody has filed an incident for yet -- that is what a new fire
    looks like for its first hours.

    Detection age is deliberately *not* a test. Four of thirteen live incidents
    had no clear overpass in the last 24 h, and dropping them would hide the
    real fires that our own staleness argument is about. The UI shows the age
    instead.
    """
    kept, dropped = [], []
    for incident in incidents:
        record = official.get(incident.id)
        if record is not None:
            reason = None if record.active else (
                "contained" if (record.contained_pct or 0) >= 100 else "record stale")
        else:
            reason = "static heat source" if is_static_source(
                incident, persistent) else None
        if reason is None:
            kept.append(incident)
        else:
            dropped.append((incident, record, reason))
    return kept, dropped


def _safe(func):
    """(value, None) or (None, "TypeName: message"). One bad fire is not a bad
    country: a national run touches LANDFIRE, HRRR and GOES per incident, and
    something is always down somewhere.

    `wraps` is not cosmetic here -- the wrapper is what the module-level name
    refers to, and pickling it for a worker process is a lookup by that name.
    """

    @wraps(func)
    def wrapped(item):
        try:
            return func(item), None
        except Exception as exc:  # noqa: BLE001 - reported per fire, not raised
            return None, f"{type(exc).__name__}: {exc}"

    return wrapped


@_safe
def _model_one(job):
    """One incident, in a worker process. Module-level so it can be pickled."""
    incident, perimeter, payload_kwargs = job
    return spread.risk_payload(bbox=incident.bbox,
                               hotspots=list(incident.hotspots),
                               perimeter=perimeter,
                               **payload_kwargs)


def merge_by_official(incidents, official: dict):
    """Clusters that are the same NIFC incident become one fire.

    A large fire's detections often break into two clusters -- a 0.05 deg gap
    between the head and a flank is enough -- and the run then models and draws
    "Border 2" twice, side by side, with two different wind readings. WFIGS
    says they carry one IRWIN id, so join their detections and let the bbox and
    the id fall out of the union.

    Returns the new incident list and the match map re-keyed to it, because
    merging moves the centroid the id is built from.
    """
    groups: dict[str, list[Incident]] = {}
    merged = []
    for incident in incidents:
        record = official.get(incident.id)
        if record is None:
            merged.append(incident)
        else:
            groups.setdefault(record.irwin_id, []).append(incident)

    matched = {}
    for irwin, parts in groups.items():
        joined = Incident(tuple(h for part in parts for h in part.hotspots))
        merged.append(joined)
        matched[joined.id] = official[parts[0].id]
    return merged, matched


def _tally(dropped) -> dict:
    """{reason: count} for the clusters that are not current wildfires."""
    counts: dict[str, int] = {}
    for _, _, reason in dropped:
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def rank(incidents, official: dict) -> list[Incident]:
    """Known wildfires first, then by radiative power.

    Radiative power alone is dominated by agriculture. On a September run the
    top twelve clusters in the country were eleven crop fires in the
    Mississippi Delta and the Dome fire -- FIRMS cannot tell the difference,
    because a burning field really is a hot 375 m pixel. A cluster WFIGS has an
    incident record for is a fire an agency is responding to, which is the one
    an evacuation map is about.

    A fire reported 100% contained sorts below the ones still open. It stays in
    the list -- contained means a line is around it, not that it is out, and
    VIIRS still sees the interior -- but it is not what an evacuation view
    should lead with.
    """
    def key(incident):
        record = official.get(incident.id)
        return (record is None, (record.contained_pct or 0) >= 100 if record else False,
                -incident.frp_mw)

    return sorted(incidents, key=key)


def _official(incidents) -> dict:
    """{incident.id: wfigs.Record}, or {} if NIFC is not answering.

    Names and perimeters make the output legible and the seed better, but the
    model runs without them. A portal outage downgrades the answer; it does not
    take the run down.
    """
    try:
        return wfigs.match(incidents, wfigs.fetch(CONUS))
    except Exception:  # noqa: BLE001 - enrichment, not a dependency
        logger.warning("WFIGS lookup failed; fires stay unnamed", exc_info=True)
        return {}


def national_payload(bbox=CONUS, limit: int = 12, workers: int = 6,
                     **payload_kwargs) -> dict:
    """A contract payload per active fire, plus what it took to find them.

    Each entry of `fires` is exactly what `/fire` returns for one incident --
    `contract.check()`ed by `risk_payload` itself -- with an added `incident`
    block saying which fire it is. Incidents that fail to model land in
    `failed` instead of taking the whole run down.
    """
    incidents, persistent = sweep(bbox)
    # Matched before the cut, not after: the point of the match is to decide
    # which fires are worth the cut in the first place.
    official = _official(incidents)
    incidents, official = merge_by_official(incidents, official)
    active, dropped = currently_active(incidents, official, persistent)
    modelled = rank(active, official)[:limit]

    fires, failed = [], []
    # Processes, not threads. `arrival_times` is a pure-Python heapq loop, so
    # it holds the GIL for its whole run: six of them in threads starved the
    # uvicorn event loop so completely that /health timed out at 20 s while a
    # national run was in flight. The per-fire work is a dict in and a dict
    # out, so it ships to a worker process unchanged. The disk caches under
    # cache/ are written atomically, which is what makes that safe.
    jobs = [(incident, getattr(official.get(incident.id), "perimeter", None),
             payload_kwargs) for incident in modelled]
    with ProcessPoolExecutor(max_workers=min(workers, len(modelled) or 1)) as pool:
        for incident, (payload, error) in zip(modelled, pool.map(_model_one, jobs)):
            record = official.get(incident.id)
            block = incident.as_dict() | (record.as_dict() if record else {})
            if error is None:
                fires.append({**payload, "incident": block})
            else:
                failed.append({**block, "error": error})

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bbox": list(bbox),
        "incidents_found": len(incidents),
        "incidents_active": len(active),
        "incidents_modelled": len(modelled),
        "named_by_wfigs": len(official),
        "excluded": _tally(dropped),
        "fires": fires,
        "failed": failed,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Model every active fire in CONUS.")
    parser.add_argument("--list", action="store_true",
                        help="discover only: no rasters, no wind, no modelling")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    if args.list:
        found = discover()
        print(f"{len(found)} incidents in CONUS\n")
        print(f"{'id':>14}  {'det':>4}  {'FRP MW':>8}  newest pass")
        for incident in found[:args.limit]:
            print(f"{incident.id:>14}  {len(incident.hotspots):>4}  "
                  f"{incident.frp_mw:>8.1f}  {firms.iso(incident.seed_time)}")
        raise SystemExit

    result = national_payload(limit=args.limit, workers=args.workers)
    excluded = ", ".join(f"{count} {reason}"
                         for reason, count in result["excluded"].items())
    print(f"{result['incidents_found']} clusters, "
          f"{result['incidents_active']} currently active"
          f"{' (excluded ' + excluded + ')' if excluded else ''}, "
          f"{len(result['fires'])} modelled, {len(result['failed'])} failed\n")
    print(f"{result['named_by_wfigs']} matched to a NIFC incident\n")
    print(f"{'fire':>22}  {'FRP MW':>8}  {'h6 km2':>8}  {'wind':>7}  toward")
    for fire in result["fires"]:
        incident, summary = fire["incident"], fire["summary"]
        label = incident.get("name", incident["id"])
        if incident.get("has_perimeter"):
            label += " *"
        print(f"{label:>22}  {incident['frp_mw']:>8.1f}  "
              f"{summary['area_km2']['h6']:>8.1f}  "
              f"{summary['wind_speed_kmh']:>5.1f}kh  "
              f"{summary['primary_spread_direction']}")
    print("\n* seeded from the official NIFC perimeter, not detections alone")
    for fire in result["failed"]:
        print(f"{fire['id']:>14}  {fire['error']}")
