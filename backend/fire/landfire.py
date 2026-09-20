"""LANDFIRE fuel and terrain, clipped and resampled by the LANDFIRE image
service so we never download a national raster.

exportImage does the clip, the reprojection and the resample in one GET, so
there is no warp code here. Output is EPSG:5070 (Albers, meters) -- the model
grid. Reprojection to EPSG:4326 happens only at export, in spread.py.

Service catalog: https://lfps.usgs.gov/arcgis/rest/services
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import numpy as np
import rasterio
from pyproj import Transformer

from .firms import DEMO_BBOX, cache_write

CACHE_DIR = Path(__file__).resolve().parent / "cache"  # gitignored
CRS = "EPSG:5070"
BASE = "https://lfps.usgs.gov/arcgis/rest/services"

# LF2016 fuel: the last vintage before the 2018 Camp Fire, so replay is not
# scored against fuel that the fire itself changed. Switch to LF2025 for live.
SERVICES = {
    "fuel": "Landfire_LF2016/LF2016_FBFM40_CONUS",
    "slope": "Landfire_Topo/LF2020_SlpD_CONUS",  # SlpD = degrees, not percent
    "aspect": "Landfire_Topo/LF2020_Asp_CONUS",  # downslope direction
}

_to_albers = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)

# F_fuel by FBFM40 group (brief's heuristic; tune against the replay fire).
# Index is the raw FBFM40 code, so lookup is fuel_factor[codes]. Anything
# unlisted -- nodata, water, code gaps -- stays 0.0 and acts as a hard barrier.
_FUEL_FACTOR = np.zeros(256, dtype="float32")
for _lo, _hi, _f in [
    (101, 110, 1.0),  # GR  grass
    (121, 125, 0.8),  # GS  grass-shrub
    (141, 150, 0.7),  # SH  shrub
    (161, 166, 0.4),  # TU  timber understory
    (181, 190, 0.2),  # TL  timber litter
    (201, 205, 0.5),  # SB  slash-blowdown
]:
    _FUEL_FACTOR[_lo:_hi] = _f

FUEL_GROUPS = {  # for the summary the LLM reads
    101: "grass", 121: "grass-shrub", 141: "shrub",
    161: "timber understory", 181: "timber litter", 201: "slash",
}


def fetch(layer: str, bbox=DEMO_BBOX, cell_m: int = 120, use_cache: bool = True,
          out_epsg: int = 5070, size: str | None = None):
    """(array, rasterio profile) for `layer` over `bbox` (W,S,E,N in EPSG:4326).

    30 m native is resampled to `cell_m`; 90-150 m is plenty for a demo and
    keeps the arrival-time search fast. Nearest-neighbour always: FBFM40 codes
    are categories, and interpolating them invents fuel models that don't exist.
    """
    west, south, east, north = _to_albers.transform_bounds(*bbox)
    size = size or f"{round((east - west) / cell_m)},{round((north - south) / cell_m)}"
    params = {
        "bbox": f"{west},{south},{east},{north}", "bboxSR": 5070,
        "imageSR": out_epsg, "size": size, "format": "tiff", "pixelType": "S16",
        "interpolation": "RSP_NearestNeighbor", "noData": -9999, "f": "image",
    }
    tag = hashlib.sha1(
        f"{layer}|{params['bbox']}|{size}|{out_epsg}".encode()).hexdigest()[:12]
    cached = CACHE_DIR / f"{layer}_{cell_m}m_{tag}.tif"

    if not (use_cache and cached.exists()):
        response = httpx.get(f"{BASE}/{SERVICES[layer]}/ImageServer/exportImage",
                             params=params, timeout=180)
        if not response.headers.get("content-type", "").startswith("image"):
            raise RuntimeError(f"LANDFIRE {layer}: {response.text[:200]}")
        cache_write(cached, response.content)

    with rasterio.open(cached) as ds:
        return ds.read(1), ds.profile


def fuel_factor(codes: np.ndarray) -> np.ndarray:
    """F_fuel per cell. Non-burnable (91-99) and nodata come back 0.0."""
    return _FUEL_FACTOR[np.clip(codes, 0, 255)]


def dominant_fuels(codes: np.ndarray, top: int = 2) -> list[str]:
    """The contract's `summary.dominant_fuels`, burnable groups only."""
    burnable = codes[fuel_factor(codes) > 0]
    if not burnable.size:
        return []
    groups = np.array([max(g for g in FUEL_GROUPS if g <= c) for c in burnable])
    values, counts = np.unique(groups, return_counts=True)
    return [FUEL_GROUPS[v] for v in values[np.argsort(-counts)][:top]]


# Overlay palette, RGBA. Keyed by the low end of each FBFM40 family. Alpha is
# low so the basemap stays readable underneath; non-burnable is the one the
# frontend actually needs to show, so it is the most opaque.
_PALETTE = [
    (91, (150, 150, 150, 170)),   # non-burnable: urban, water, ag, barren
    (101, (247, 224, 138, 120)),  # grass
    (121, (212, 191, 79, 120)),   # grass-shrub
    (141, (160, 82, 45, 130)),    # shrub
    (161, (27, 94, 32, 130)),     # timber understory
    (181, (124, 179, 66, 120)),   # timber litter
    (201, (109, 76, 65, 130)),    # slash
]


def overlay_png(path, bbox=DEMO_BBOX, width: int = 600) -> dict:
    """Write a fuel-layer PNG for the map, and return its EPSG:4326 bounds.

    Rendered in EPSG:4326, not the 5070 model grid: a web map stretches an
    image overlay across a lat/lon rectangle, so an Albers image would arrive
    visibly skewed. Returns bounds in the [[south, west], [north, east]] order
    Leaflet's imageOverlay expects.

    600 px is ~62 m per pixel, still finer than the 120 m model grid. Going to
    900 px triples the file (111 KB -> 307 KB) for detail the model does not
    have: the cost is fuel speckle, not colour depth, so palette mode does not
    help and would cost the per-class alpha.
    """
    from PIL import Image

    west, south, east, north = bbox
    height = round(width * (north - south) / (east - west))
    codes, _ = fetch("fuel", bbox=bbox, out_epsg=4326, size=f"{width},{height}")

    rgba = np.zeros((*codes.shape, 4), dtype="uint8")  # nodata stays transparent
    for low, colour in _PALETTE:
        high = next((n for n, _ in _PALETTE if n > low), 256)
        rgba[(codes >= low) & (codes < high)] = colour

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    return {
        "image": path.name,
        "bounds": [[south, west], [north, east]],
        "crs": "EPSG:4326",
        "size": [width, height],
        "legend": {name: f"#{r:02x}{g:02x}{b:02x}" for (low, (r, g, b, _)), name
                   in zip(_PALETTE, ["non-burnable", "grass", "grass-shrub", "shrub",
                                     "timber understory", "timber litter", "slash"])},
        "note": "LANDFIRE LF2016 FBFM40, grouped by fuel family. Display only -- "
                "the model runs on the 30 m source in EPSG:5070.",
    }


if __name__ == "__main__":
    import json
    import sys

    if "--overlay" in sys.argv:
        out = Path(__file__).resolve().parents[2] / "demo_data" / "fuel_overlay.png"
        meta = overlay_png(out)
        meta_path = out.with_suffix(".json")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
        print(f"wrote {meta_path}")
        print(json.dumps({k: meta[k] for k in ("bounds", "size")}, indent=2))
        sys.exit()

    codes, profile = fetch("fuel")
    factors = fuel_factor(codes)
    print(f"{profile['crs']} {codes.shape} at {profile['transform'].a:.1f} m")
    print(f"burnable: {100 * (factors > 0).mean():.1f}% of cells")
    print(f"dominant_fuels: {dominant_fuels(codes)}")
