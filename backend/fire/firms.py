"""NASA FIRMS active-fire detections: fetch, parse, and hand back ignition seeds.

A FIRMS row is a *pixel*, not a perimeter -- VIIRS pixels are ~375 m, MODIS ~1 km.
Downstream these points get rasterized (or buffered by half a pixel) to seed
ignition cells; nothing here pretends a point is a fire boundary.

`acq_time` is carried through untouched so the UI can say "hotspots as of 12:41".

Area API reference: https://firms.modaps.eosdis.nasa.gov/api/area/
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

BASE = "https://firms.modaps.eosdis.nasa.gov/api"
CACHE_DIR = Path(__file__).resolve().parent / "cache"  # gitignored
REPO_ROOT = Path(__file__).resolve().parents[2]

# west, south, east, north -- the order the FIRMS area API wants.
DEMO_BBOX = (-121.80, 39.60, -121.40, 39.95)  # Camp Fire origin, Butte County CA

# NRT is the live feed; SP (standard processing) is the reprocessed archive used
# for replay. SP lags NRT by roughly two months -- call data_availability()
# rather than guessing where the cutoff is today.
LIVE_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT")
ARCHIVE_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP")

MAX_DAY_RANGE = 5  # hard limit of the area API

# FIRMS `type`: 0 presumed vegetation fire, 1 active volcano,
# 2 other static land source, 3 offshore.
VEGETATION_FIRE = 0


class FirmsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Hotspot:
    lon: float
    lat: float
    confidence: str  # normalized to "l" / "n" / "h" across sensors
    frp: float  # fire radiative power, MW
    acq_time: datetime  # UTC
    sensor: str
    source: str

    def as_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lon, self.lat]},
            "properties": {
                "confidence": self.confidence,
                "frp": self.frp,
                "acq_time": iso(self.acq_time),
                "sensor": self.sensor,
            },
        }


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def map_key() -> str:
    """FIRMS MAP_KEY from the environment, falling back to the repo's .env.

    Values in .env may be quoted; strip them. A quoted key reaches the API with
    the quotes attached and comes back as a flat "Invalid MAP_KEY." with no hint
    that the key itself is fine.
    """
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        env = REPO_ROOT / ".env"
        if env.exists():
            match = re.search(
                r"^\s*FIRMS_MAP_KEY\s*=\s*(.+?)\s*$",
                env.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            key = match.group(1) if match else None
    key = (key or "").strip().strip("'\"")
    if not key or key == "your_key_here":
        raise FirmsError(
            "No FIRMS MAP_KEY. Copy .env.example to .env and fill it in "
            "(free key: https://firms.modaps.eosdis.nasa.gov/api/map_key/)."
        )
    return key


def _get(path: str, *, timeout: float = 90.0) -> str:
    """GET against the FIRMS API. Never let the key into an error message."""
    key = map_key()
    url = f"{BASE}/{path.format(key=key)}"
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise FirmsError(f"FIRMS request failed: {type(exc).__name__}") from None
    body = response.text
    # FIRMS answers some failures with 200 and a plain-text complaint.
    if response.status_code != 200 or not body.lstrip().lower().startswith("lat"):
        detail = body.strip()[:200].replace(key, "<MAP_KEY>")
        raise FirmsError(f"FIRMS {response.status_code}: {detail}")
    return body


def data_availability() -> dict[str, tuple[str, str]]:
    """{source: (min_date, max_date)} -- check before picking a replay date."""
    key = map_key()
    response = httpx.get(f"{BASE}/data_availability/csv/{key}/ALL", timeout=60)
    if response.status_code != 200:
        raise FirmsError(f"FIRMS {response.status_code}: availability lookup failed")
    rows = csv.DictReader(io.StringIO(response.text))
    return {r["data_id"]: (r["min_date"], r["max_date"]) for r in rows}


def _normalize_confidence(raw: str) -> str:
    """VIIRS reports l/n/h; MODIS reports 0-100. Collapse to l/n/h."""
    raw = raw.strip().lower()
    if raw in ("l", "n", "h"):
        return raw
    try:
        pct = float(raw)
    except ValueError:
        return "n"
    if pct < 30:
        return "l"
    return "h" if pct > 80 else "n"


def _parse_row(row: dict, source: str) -> Hotspot:
    # acq_time is UTC HHMM, and drops leading zeros ("50" means 00:50).
    hhmm = row["acq_time"].strip().zfill(4)
    stamp = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M")
    return Hotspot(
        lon=float(row["longitude"]),
        lat=float(row["latitude"]),
        confidence=_normalize_confidence(row["confidence"]),
        frp=float(row["frp"]),
        acq_time=stamp.replace(tzinfo=timezone.utc),
        sensor=f"{row['instrument']}/{row['satellite']}",
        source=source,
    )


def fetch_hotspots(
    bbox: tuple[float, float, float, float] = DEMO_BBOX,
    source: str = "VIIRS_SNPP_NRT",
    start_date: date | str | None = None,
    days: int = 1,
    *,
    vegetation_only: bool = True,
    use_cache: bool = True,
) -> list[Hotspot]:
    """Hotspots inside `bbox` (west, south, east, north), EPSG:4326.

    `start_date` of None means "the most recent available data". `days` is
    capped at 5 by the API; call again with a later start_date for longer
    spans. Fixed-date responses are cached on disk -- the MAP_KEY allows 5000
    requests per 10 minutes and a replay loop burns through that faster than
    you would think. NRT results are never cached, since that feed moves.
    """
    if not 1 <= days <= MAX_DAY_RANGE:
        raise ValueError(f"days must be 1..{MAX_DAY_RANGE} (API limit), got {days}")
    west, south, east, north = bbox
    if not (west < east and south < north):
        raise ValueError(f"bbox must be (west, south, east, north), got {bbox}")

    when = start_date.isoformat() if isinstance(start_date, date) else start_date
    area = f"{west},{south},{east},{north}"
    path = f"area/csv/{{key}}/{source}/{area}/{days}"
    if when:
        path += f"/{when}"

    # Cache key excludes the MAP_KEY, so the filename is safe to look at.
    tag = hashlib.sha1(f"{source}|{area}|{days}|{when}".encode()).hexdigest()[:12]
    cached = CACHE_DIR / f"{source}_{when or 'latest'}_{tag}.csv"
    if use_cache and when and cached.exists():
        body = cached.read_text(encoding="utf-8")
    else:
        body = _get(path)
        if use_cache and when:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_text(body, encoding="utf-8")

    hotspots = []
    for row in csv.DictReader(io.StringIO(body)):
        if vegetation_only and int(row.get("type", VEGETATION_FIRE)) != VEGETATION_FIRE:
            continue
        hotspots.append(_parse_row(row, source))
    hotspots.sort(key=lambda h: h.acq_time)
    return hotspots


def fetch_many(
    sources: tuple[str, ...] = ARCHIVE_SOURCES, **kwargs
) -> list[Hotspot]:
    """Union of several sensors. More passes per day means finer spread timing.

    Detections are not deduplicated: overlapping sensors see the same pixel
    slightly differently, and rasterizing the union is more honest than
    picking a winner.
    """
    hotspots: list[Hotspot] = []
    for source in sources:
        hotspots.extend(fetch_hotspots(source=source, **kwargs))
    hotspots.sort(key=lambda h: h.acq_time)
    return hotspots


def to_feature_collection(hotspots: list[Hotspot]) -> dict:
    """The contract's `fire_points` block."""
    return {
        "type": "FeatureCollection",
        "features": [h.as_feature() for h in hotspots],
    }


def latest_acq_time(hotspots: list[Hotspot]) -> str | None:
    """The contract's `data_as_of.firms` -- newest observation, not fetch time."""
    return iso(max(h.acq_time for h in hotspots)) if hotspots else None


def _summarize(hotspots: list[Hotspot]) -> None:
    from collections import Counter

    if not hotspots:
        print("no detections")
        return
    passes = sorted(Counter(h.acq_time for h in hotspots).items())
    print(f"{len(hotspots)} detections over {len(passes)} satellite passes")
    print(f"confidence: {dict(Counter(h.confidence for h in hotspots))}")
    print(f"sensors:    {dict(Counter(h.sensor for h in hotspots))}")
    print(f"frp MW:     {min(h.frp for h in hotspots):.1f} .. "
          f"{max(h.frp for h in hotspots):.1f}")
    print(f"extent:     lon {min(h.lon for h in hotspots):.4f}.."
          f"{max(h.lon for h in hotspots):.4f}  "
          f"lat {min(h.lat for h in hotspots):.4f}..{max(h.lat for h in hotspots):.4f}")
    print(f"data_as_of.firms: {latest_acq_time(hotspots)}")
    print("passes:")
    for stamp, count in passes:
        print(f"  {iso(stamp)}  {count:>5}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch FIRMS hotspots for the demo area.")
    parser.add_argument("--date", help="YYYY-MM-DD; omit for the latest available")
    parser.add_argument("--days", type=int, default=1, help=f"1..{MAX_DAY_RANGE}")
    parser.add_argument("--live", action="store_true",
                        help="use NRT sources instead of the SP archive")
    args = parser.parse_args()

    sources = LIVE_SOURCES if args.live else ARCHIVE_SOURCES
    if not args.date and not args.live:
        print("no --date given; SP archive lags ~2 months, availability:")
        for name, (lo, hi) in data_availability().items():
            if name in sources:
                print(f"  {name}: {lo} .. {hi}")
    _summarize(fetch_many(sources, start_date=args.date, days=args.days))
