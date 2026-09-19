"""Palisades Fire, January 2025: this engine against the standard model and the truth.

Three windows on the fire's first two days. Each model is fitted once, on the
first window, and scored on the two after it -- fitting and scoring the same
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
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from . import elliptical, firms, validate

UTC = timezone.utc
BBOX = (-118.72, 34.00, -118.47, 34.16)
DEMO_DATA = Path(__file__).resolve().parents[2] / "demo_data"
PERIMETER = DEMO_DATA / "palisades_nifc_perimeter.geojson"
FIGURE = DEMO_DATA / "palisades_comparison.png"

# (seed pass, validate pass). VIIRS gives no pass in between, so ~12 h is the
# shortest honest window on this fire -- not a choice.
WINDOWS = [
    (datetime(2025, 1, 7, 21, 27, tzinfo=UTC), datetime(2025, 1, 8, 9, 26, tzinfo=UTC)),
    (datetime(2025, 1, 8, 9, 49, tzinfo=UTC), datetime(2025, 1, 8, 20, 45, tzinfo=UTC)),
    (datetime(2025, 1, 8, 21, 8, tzinfo=UTC), datetime(2025, 1, 9, 9, 7, tzinfo=UTC)),
]

# dataviz categorical slots 1-3, the set validated for all-pairs separation.
IGNIS, FARSITE, HOMOGENEOUS = "#2a78d6", "#eb6834", "#1baf7a"
BURNED, SEED, INK, MUTED = "#3d3d3a", "#b8b7b0", "#0b0b0b", "#52514e"
SURFACE, RULE, GRID = "#fcfcfb", "#dededa", "#e8e8e4"


def models(wind):
    ellipse = elliptical.step_factors(wind.speed_kmh, wind.toward_deg)
    return {
        "Ignis": dict(use_fuel=True, use_slope=True, sf=None),
        "FARSITE-class": dict(use_fuel=True, use_slope=True, sf=ellipse),
        "FARSITE-class, no fuel/slope": dict(use_fuel=False, use_slope=False,
                                             sf=ellipse),
    }


def run(peak_window_h: int = 8) -> dict:
    """Fit on window 1, score on 2 and 3. Predictions are kept for the figure."""
    setups = [validate._setup(s, v, BBOX, peak_window_h) for s, v in WINDOWS]
    fit = setups[0]
    configured = models(fit["wind"])

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
        for name, cfg in configured.items():
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
    print(f"\nwrote {figure(result)}")
