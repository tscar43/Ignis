"""GOES ABI fire detections: the same fire every 5 minutes instead of twice a day.

VIIRS gives ~4 passes a day at 375 m. On a live run over the Sierra on
2026-09-19 the newest pass was **nine hours old**, so the model projected six
hours forward from a nine-hour-old footprint and labelled the result "h6".
That staleness, not the spread physics, is the largest error term in a live
payload.

GOES ABI's Fire Detection and Characterization product scans CONUS every five
minutes and the file lands in a public S3 bucket about three minutes after the
scan starts. The trade is resolution: ~2 km at nadir, nearer 4 km over
California, against VIIRS's 375 m. ABI also only sees the hottest cores, so it
under-reports footprint where VIIRS over-reports staleness.

So this is a freshness source, not a replacement. `spread.gather()` unions the
newest ABI frame with the newest VIIRS pass: ABI says where the fire is *now*,
VIIRS's finer pixels say how big it is.

Anonymous S3 -- no key, no registration. rasterio reads the netCDF and pyproj
handles the geostationary projection, so there is no new dependency either.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import rasterio
from pyproj import Transformer

from .firms import CACHE_DIR, DEMO_BBOX, Hotspot

# GOES-West sees the western US, GOES-East the rest. FDCC is the CONUS sector,
# scanned every 5 minutes; FDCF is full disk at 10 and FDCM mesoscale at 1.
WEST, EAST = "noaa-goes18", "noaa-goes19"
PRODUCT = "ABI-L2-FDCC"

# ponytail: one isotropic number for a footprint that is ~2 km at nadir and
# anisotropic off it (~2.8 x 4.4 km over California). The file carries a
# per-pixel `Area`; read it if the seed edge ever needs to be better than this.
PIXEL_M = 3000.0

# Mask values that mean fire. The 3x codes are the temporally filtered
# counterparts of the 1x ones -- same categories, confirmed across frames.
# Everything below 10 is cloud, water, or clear ground.
FIRE_CONFIDENCE = {
    10: "h", 11: "h", 12: "n", 13: "h", 14: "n", 15: "l",   # good, saturated,
    30: "h", 31: "h", 32: "n", 33: "h", 34: "n", 35: "l",   # cloudy, hi/med/lo
}


class GoesError(RuntimeError):
    pass


def bucket_for(lon: float) -> str:
    """Which satellite sees this longitude. GOES-18 sits at 137W, GOES-19 at 75W."""
    return WEST if lon < -105 else EAST


def scan_start(name: str) -> datetime:
    """`OR_ABI-L2-FDCC-M6_G18_s20262622001177_...` -> the s field, UTC.

    Year, day-of-year, then HHMMSS and a tenth of a second. Day-of-year, not
    month-day: parsing it as %Y%m%d silently lands in the wrong month.
    """
    match = re.search(r"_s(\d{4})(\d{3})(\d{6})", name)
    if not match:
        raise GoesError(f"not a GOES filename: {name}")
    return datetime.strptime("".join(match.groups()), "%Y%j%H%M%S").replace(
        tzinfo=timezone.utc)


def latest_key(bucket: str, when: datetime) -> str | None:
    """Newest FDCC object in `when`'s hour, or None if that hour is empty.

    Keys sort by their own timestamp, so max() is the newest and there is no
    reason to parse the listing XML.
    """
    prefix = f"{PRODUCT}/{when:%Y}/{when.timetuple().tm_yday:03d}/{when:%H}/"
    listing = httpx.get(f"https://{bucket}.s3.amazonaws.com/", timeout=60,
                        params={"list-type": "2", "prefix": prefix}).text
    keys = re.findall(r"<Key>([^<]+\.nc)</Key>", listing)
    return max(keys) if keys else None


def fetch(bbox=DEMO_BBOX, when: datetime | None = None) -> list[Hotspot]:
    """Fire pixels inside `bbox` from the newest ABI frame. [] if there are none.

    An empty list is the normal answer, not an error: most frames over most
    boxes see no fire, and the caller falls back to VIIRS alone.
    """
    when = when or datetime.now(timezone.utc)
    bucket = bucket_for((bbox[0] + bbox[2]) / 2)
    # Just after the hour the current prefix can still be empty.
    key = latest_key(bucket, when) or latest_key(bucket, when - timedelta(hours=1))
    if key is None:
        return []

    # Cached by scan time, which is in the filename, so a hit is never stale.
    # ponytail: nothing prunes cache/; ~280 KB per frame, and it is gitignored.
    path = CACHE_DIR / key.rsplit("/", 1)[-1]
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(httpx.get(f"https://{bucket}.s3.amazonaws.com/{key}",
                                   timeout=90).content)

    with rasterio.open(f'netcdf:"{path}":Mask') as dataset:
        mask, transform, crs = dataset.read(1), dataset.transform, dataset.crs
    with rasterio.open(f'netcdf:"{path}":Power') as dataset:
        power = dataset.read(1, masked=True).filled(0.0)
    return to_hotspots(mask, power, transform, crs, bbox,
                       scan_start(path.name), bucket)


def to_hotspots(mask, power, transform, crs, bbox, acq_time, bucket) -> list[Hotspot]:
    """Fire-flagged cells of an ABI grid as Hotspots, clipped to `bbox`.

    Split out from `fetch` so the geolocation and the mask decoding are
    testable without a 280 KB netCDF fixture.
    """
    rows, cols = np.nonzero(np.isin(mask, list(FIRE_CONFIDENCE)))
    if not len(rows):
        return []
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lons, lats = to_wgs84.transform(np.asarray(xs), np.asarray(ys))

    west, south, east, north = bbox
    satellite = bucket.removeprefix("noaa-").upper()
    return [
        Hotspot(lon=float(lon), lat=float(lat),
                confidence=FIRE_CONFIDENCE[int(mask[row, col])],
                frp=round(float(power[row, col]), 1),
                acq_time=acq_time, sensor=f"ABI/{satellite}",
                source=f"{satellite}_{PRODUCT}", pixel_m=PIXEL_M)
        for lon, lat, row, col in zip(lons, lats, rows, cols)
        if west <= lon <= east and south <= lat <= north
    ]


if __name__ == "__main__":
    import sys

    box = DEMO_BBOX
    if len(sys.argv) == 5:
        box = tuple(float(a) for a in sys.argv[1:])
    hotspots = fetch(box)
    if not hotspots:
        print(f"no ABI fire pixels in {box} in the newest frame")
        raise SystemExit
    age = datetime.now(timezone.utc) - hotspots[0].acq_time
    print(f"{len(hotspots)} fire pixels, scan {hotspots[0].acq_time:%Y-%m-%dT%H:%M:%SZ} "
          f"({age.total_seconds() / 60:.0f} min old)")
    print(f"sensor: {hotspots[0].sensor}  total frp: "
          f"{sum(h.frp for h in hotspots):.1f} MW")
    for h in hotspots:
        print(f"  {h.lat:8.4f},{h.lon:10.4f}  {h.confidence}  {h.frp:7.1f} MW")
