"""Palisades Fire, January 2025: this engine against the standard model and the truth.

Four windows on the fire's first three days. Each model is fitted once, on the
first window, and scored on the three after it -- fitting and scoring the same
window would make every IoU a restatement of the calibration, which is the rule
`validate.py` already works under.

On the third comparison the honest answer is that it cannot be done from public
data. No vendor publishes its spread predictions for a historical fire, so
"compare against a commercial model" is not retrievable. What is public is the
formulation underneath them -- see `elliptical.py`. The baseline here is that
formulation, run through this engine's own solver on the same seed, wind and
grid, so the only thing that differs is the shape of the wind term. It is not a
claim about what any vendor's product would have produced.

Ground truth is the union of FIRMS detections up to the validation pass, the
same mask `validate.py` scores against, with the NIFC final perimeter drawn for
reference. That perimeter is the whole fire, 23,448 acres over three weeks; the
windows here are twelve hours each, so it is context, not the target.

    ./.venv/Scripts/python.exe -m backend.fire.palisades
    ./.venv/Scripts/python.exe -m backend.fire.palisades --json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio.features
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from . import elliptical, firms, validate
from .spread import _round_coords

UTC = timezone.utc
BBOX = (-118.72, 34.00, -118.47, 34.16)
DEMO_DATA = Path(__file__).resolve().parents[2] / "demo_data"
PERIMETER = DEMO_DATA / "palisades_nifc_perimeter.geojson"
FIGURE = DEMO_DATA / "palisades_comparison.png"
REPLAY = DEMO_DATA / "palisades_replay.json"

# (seed pass, validate pass). Every timestamp is a real VIIRS overpass over
# this bbox; ~12 h is the shortest honest window the cadence allows, not a
# choice. Seed on the later pass of an overpass pair, validate on the earlier
# pass of the next -- the longest gap that stays inside one pair-to-pair step.
WINDOWS = [
    (datetime(2025, 1, 7, 21, 27, tzinfo=UTC), datetime(2025, 1, 8, 9, 26, tzinfo=UTC)),
    (datetime(2025, 1, 8, 9, 49, tzinfo=UTC), datetime(2025, 1, 8, 20, 45, tzinfo=UTC)),
    (datetime(2025, 1, 8, 21, 8, tzinfo=UTC), datetime(2025, 1, 9, 9, 7, tzinfo=UTC)),
    (datetime(2025, 1, 9, 9, 30, tzinfo=UTC), datetime(2025, 1, 9, 20, 26, tzinfo=UTC)),
]

# dataviz categorical slots 1-3, the set validated for all-pairs separation.
IGNIS, FARSITE, HOMOGENEOUS = "#2a78d6", "#eb6834", "#1baf7a"
BURNED, SEED, INK, MUTED = "#3d3d3a", "#b8b7b0", "#0b0b0b", "#52514e"
SURFACE, RULE, GRID = "#fcfcfb", "#dededa", "#e8e8e4"


def models(wind, convergence_deg: float = 0.0):
    """The three configurations, with the ellipse built for THIS window's wind.

    Recomputed per window rather than once: Ignis reads its wind out of each
    window's setup, so an ellipse frozen at the calibration window would be
    answering a different question from the model it is being compared with,
    and the "same seed, same wind, only the shape differs" claim would be
    false. Only R0 is carried across windows, because that is the one thing
    calibration is allowed to fix.
    """
    ellipse = elliptical.step_factors(wind.speed_kmh, wind.toward_deg,
                                      convergence_deg)
    return {
        "Ignis": dict(use_fuel=True, use_slope=True, sf=None),
        "FARSITE-class": dict(use_fuel=True, use_slope=True, sf=ellipse),
        "FARSITE-class, no fuel/slope": dict(use_fuel=False, use_slope=False,
                                             sf=ellipse),
    }


def run(peak_window_h: int = 8) -> dict:
    """Fit on window 1, score on the rest. Predictions are kept for the figure."""
    setups = [validate._setup(s, v, BBOX, peak_window_h) for s, v in WINDOWS]
    fit = setups[0]
    configured = models(fit["wind"], fit["convergence"])

    r0 = {name: validate.calibrate(fit, cfg["use_fuel"], cfg["use_slope"],
                                   fit["truth"].sum() * fit["cell_km2"],
                                   step_factors=cfg["sf"])
          for name, cfg in configured.items()}

    windows = []
    for index, (setup, (seed_at, validate_at)) in enumerate(zip(setups, WINDOWS)):
        window = {
            "seed_at": firms.iso(seed_at), "validate_at": firms.iso(validate_at),
            "role": "fit" if index == 0 else "scored",
            "gap_h": round(setup["gap_min"] / 60, 1),
            "wind_kmh": setup["wind"].speed_kmh,
            "wind_toward": round(setup["wind"].toward_deg),
            "seed_km2": round(setup["ignition"].sum() * setup["cell_km2"], 1),
            "observed_km2": round(setup["truth"].sum() * setup["cell_km2"], 1),
            "models": {}, "predictions": {}, "setup": setup,
        }
        for name, cfg in models(setup["wind"], setup["convergence"]).items():
            predicted = validate._predict(setup, cfg["use_fuel"], cfg["use_slope"],
                                          r0[name], cfg["sf"])
            window["models"][name] = {
                "r0": r0[name],
                "predicted_km2": round(predicted.sum() * setup["cell_km2"], 1),
                "iou": round(validate.iou(predicted, setup["truth"]), 3),
                "iou_growth": round(validate.iou(predicted & ~setup["ignition"],
                                                 setup["truth"] & ~setup["ignition"]), 3),
            }
            window["predictions"][name] = predicted
        windows.append(window)

    return {"windows": windows, "r0": r0,
            "lb": round(elliptical.length_to_breadth(fit["wind"].speed_kmh), 2)}


def mask_to_fc(mask: np.ndarray, transform, simplify_m: float = 120.0,
               close_m: float = 150.0, ndigits: int = 5) -> dict:
    """One boolean mask as an EPSG:4326 FeatureCollection, [lon, lat].

    Same recipe as `spread.bands_to_geojson` minus the cumulative-band pass,
    which these masks have no equivalent of: polygonize in metres, close the
    pinhole lattice that 375 m detection pixels leave behind, simplify, then
    reproject. Tolerance is coarser and rounding shorter than the live
    contract's, because this one is a fixture a browser downloads whole.
    """
    to_wgs = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True).transform
    pieces = [shape(geom) for geom, value in rasterio.features.shapes(
        mask.astype("uint8"), mask=mask, transform=transform) if value == 1]
    if not pieces:
        return {"type": "FeatureCollection", "features": []}
    geom = (unary_union(pieces).buffer(close_m).buffer(-close_m)
            .simplify(simplify_m).buffer(0))
    geom = shapely_transform(to_wgs, geom)
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {},
         "geometry": _round_coords(mapping(part), ndigits)}
        for part in parts if not part.is_empty]}


def export(result: dict, path: Path = REPLAY) -> Path:
    """Every window as GeoJSON, for the frontend's stepped replay.

    A static fixture on purpose: the demo tab must not hang on a FIRMS round
    trip mid-presentation. Regenerate with `--json` when WINDOWS moves.
    """
    windows = []
    for window in result["windows"]:
        setup = window["setup"]
        transform = setup["transform"]
        windows.append({key: window[key] for key in (
            "seed_at", "validate_at", "role", "gap_h", "wind_kmh",
            "wind_toward", "seed_km2", "observed_km2", "models")} | {
            "seed": mask_to_fc(setup["ignition"], transform),
            "observed": mask_to_fc(setup["truth"], transform),
            "predictions": {name: mask_to_fc(predicted, transform)
                            for name, predicted in window["predictions"].items()},
        })
    path.write_text(json.dumps({
        "fire": "Palisades Fire, Los Angeles County, California",
        "generated_at": firms.iso(datetime.now(UTC)),
        "reseeding": (f"Every window re-seeds from the observed FIRMS "
                      f"footprint at its own seed pass, never from the "
                      f"previous prediction. These are {len(windows)} "
                      f"independent ~12 h forecasts, not one "
                      f"{round(sum(w['gap_h'] for w in windows))} h run."),
        "perimeter": ("NIFC's final perimeter is the whole 23,448-acre fire "
                      "over three weeks. Reference context, not the target "
                      "these windows are scored against."),
        "r0_m_per_min": result["r0"], "length_to_breadth": result["lb"],
        "colors": {"Ignis": IGNIS, "FARSITE-class": FARSITE,
                   "FARSITE-class, no fuel/slope": HOMOGENEOUS,
                   "observed": BURNED, "seed": SEED},
        "windows": windows,
    }, separators=(",", ":")), encoding="utf-8")
    return path


def _perimeter_5070():
    geometry = shape(json.loads(PERIMETER.read_text())["features"][0]["geometry"])
    to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    return shapely_transform(lambda x, y: to_albers.transform(x, y), geometry)


def _extent(transform, shape_):
    rows, cols = shape_
    return (transform.c, transform.c + transform.a * cols,
            transform.f + transform.e * rows, transform.f)


def _crop(masks, transform, perimeter, margin: float = 0.06):
    """Axis limits around the fire. The fetch bbox is mostly empty ocean and
    city, and drawing all of it shrinks the part anyone needs to read."""
    rows, cols = np.nonzero(np.logical_or.reduce(masks))
    xs = transform.c + transform.a * np.array([cols.min(), cols.max() + 1])
    ys = transform.f + transform.e * np.array([rows.max() + 1, rows.min()])
    west, south, east, north = perimeter.bounds
    west, east = min(west, xs[0]), max(east, xs[1])
    south, north = min(south, ys[0]), max(north, ys[1])
    pad = max(east - west, north - south) * margin
    return (west - pad, east + pad), (south - pad, north + pad)


def figure(result: dict, window_index: int = 2) -> Path:
    """Maps of one window, plus every window's score so nothing is cherry-picked."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    window = result["windows"][window_index]
    setup = window["setup"]
    extent = _extent(setup["transform"], setup["truth"].shape)
    perimeter = _perimeter_5070()

    fig = plt.figure(figsize=(13.5, 8.0), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    grid = fig.add_gridspec(2, 3, height_ratios=[1.12, 1.0], hspace=0.38,
                            wspace=0.06, left=0.045, right=0.965,
                            top=0.815, bottom=0.085)

    xlim, ylim = _crop([setup["truth"]] + list(window["predictions"].values()),
                       setup["transform"], perimeter)

    panels = [("Ignis", IGNIS), ("FARSITE-class", FARSITE), ("Actual", BURNED)]
    for column, (name, color) in enumerate(panels):
        ax = fig.add_subplot(grid[0, column])
        ax.set_facecolor(SURFACE)
        truth_panel = name == "Actual"
        mask = setup["truth"] if truth_panel else window["predictions"][name]

        # Seed underneath: all three share it, so what separates the panels is
        # the growth rather than the starting footprint.
        for layer, tint in ((setup["ignition"], SEED),
                            (mask & ~setup["ignition"], color)):
            ax.imshow(np.ma.masked_where(~layer, layer), extent=extent,
                      cmap=ListedColormap([tint]), interpolation="nearest",
                      vmin=0, vmax=1)

        for piece in getattr(perimeter, "geoms", [perimeter]):
            ax.plot(*piece.exterior.xy, color=INK, linewidth=0.7, alpha=0.5, zorder=5)

        if truth_panel:
            subtitle = (f"{window['observed_km2']:.0f} km2 detected by "
                        f"{window['validate_at'][11:16]}Z")
        else:
            stats = window["models"][name]
            subtitle = (f"{stats['predicted_km2']:.0f} km2   "
                        f"growth IoU {stats['iou_growth']:.3f}")
            # Truth outline on the prediction panels, so the score is legible
            # as a picture and not only as a number.
            ax.contour(setup["truth"][::-1], levels=[0.5], colors=[BURNED],
                       linewidths=0.9, extent=extent, zorder=4)

        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(name, fontsize=13, color=INK, pad=9)
        ax.text(0.5, -0.04, subtitle, transform=ax.transAxes, ha="center",
                va="top", fontsize=9.5, color=MUTED)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(RULE)

    bars = fig.add_subplot(grid[1, :])
    bars.set_facecolor(SURFACE)
    names = list(result["r0"])
    width, positions = 0.26, np.arange(len(result["windows"]))
    for offset, (name, color) in enumerate(zip(names, (IGNIS, FARSITE, HOMOGENEOUS))):
        values = [w["models"][name]["iou_growth"] for w in result["windows"]]
        x = positions + (offset - 1) * width
        bars.bar(x, values, width * 0.92, color=color, label=name, zorder=3)
        for xi, value in zip(x, values):
            bars.text(xi, value + 0.006, f"{value:.3f}", ha="center", va="bottom",
                      fontsize=8.5, color=MUTED)

    bars.set_xticks(positions)
    bars.set_xticklabels(
        [f"{w['seed_at'][5:16].replace('T', ' ')}Z  +{w['gap_h']:.0f} h\n"
         f"{w['wind_kmh']:.0f} km/h toward {w['wind_toward']}"
         f"   {'(R0 fitted here)' if w['role'] == 'fit' else '(held out)'}"
         for w in result["windows"]], fontsize=9, color=MUTED)
    bars.set_ylabel("growth IoU", fontsize=10, color=MUTED)
    bars.set_ylim(0, max(w["models"][n]["iou_growth"]
                         for w in result["windows"] for n in names) * 1.24)
    bars.tick_params(axis="y", labelsize=9, colors=MUTED)
    bars.tick_params(axis="x", length=0)
    bars.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    bars.set_axisbelow(True)
    for side in ("top", "right", "left"):
        bars.spines[side].set_visible(False)
    bars.spines["bottom"].set_edgecolor(RULE)
    bars.legend(frameon=False, fontsize=9.5, labelcolor=MUTED, ncol=3,
                loc="upper center", bbox_to_anchor=(0.5, 1.15))

    fig.text(0.045, 0.955, "Palisades Fire, 7-9 January 2025", fontsize=17, color=INK)
    for offset, line in enumerate([
            f"Maps: seeded {window['seed_at'][:16].replace('T', ' ')}Z and projected "
            f"{window['gap_h']:.0f} h, on a window held out of calibration.",
            "FARSITE-class is the Alexander/Finney ellipse run through the same solver, "
            "seed and wind: the published formulation",
            "commercial tools are built on, not any vendor's output."]):
        fig.text(0.045, 0.912 - offset * 0.027, line, fontsize=9.2, color=MUTED)

    fig.legend(handles=[Patch(facecolor=SEED, label="seed (shared)"),
                        Line2D([0], [0], color=BURNED, lw=1.2,
                               label="observed footprint at the validation pass"),
                        Line2D([0], [0], color=INK, lw=0.8, alpha=0.5,
                               label="NIFC final perimeter, 23,448 acres")],
               frameon=False, fontsize=9, labelcolor=MUTED, ncol=1,
               loc="upper right", bbox_to_anchor=(0.968, 0.938))

    fig.savefig(FIGURE, facecolor=fig.get_facecolor())
    plt.close(fig)
    return FIGURE


if __name__ == "__main__":
    import sys

    result = run()
    print("fitted R0 (m/min): "
          + ", ".join(f"{name} {value}" for name, value in result["r0"].items()))
    print(f"ellipse length:breadth at the fit window: {result['lb']}")
    for window in result["windows"]:
        print(f"\n{window['role']:>6}  {window['seed_at']} -> {window['validate_at']} "
              f"(+{window['gap_h']} h)  wind {window['wind_kmh']} km/h toward "
              f"{window['wind_toward']}  seed {window['seed_km2']} km2  "
              f"observed {window['observed_km2']} km2")
        for name, stats in window["models"].items():
            print(f"    {name:30} {stats['predicted_km2']:6.1f} km2  "
                  f"IoU {stats['iou']:.3f}  growth {stats['iou_growth']:.3f}")
    if "--json" in sys.argv:
        print(f"\nwrote {export(result)}")
    else:
        print(f"\nwrote {figure(result)}")
