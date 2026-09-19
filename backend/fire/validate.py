"""IoU of predicted risk bands against what the fire actually did.

Ground truth here is the union of FIRMS detections up to the validation time,
rasterized exactly the way ignition seeds are. That is deliberate but limited:
a detection is an *actively burning* pixel, so a cell that burned and cooled
stops being reported. The observed footprint therefore understates burned
area, and the absolute IoU is pessimistic. The ablation -- wind only vs
+fuel vs +fuel+slope, all scored the same way -- is the honest comparison,
because the bias cancels.

Each configuration is calibrated separately before scoring. Sharing one R0
would make the ablation meaningless -- adding F_fuel only slows the model
down, so IoU would measure spread rate rather than whether the fuel term puts
fire in better places. Fit on one day, score on the next; `FIRES` holds both.

RESULT, recorded honestly because it is not what we expected: the fuel and
slope terms do NOT improve IoU, on either fire. Growth-only IoU:

                        Camp 2018-11-09       Dixie 2021-07-16
                      +1.7 h     +11.4 h     +1.7 h     +10.5 h
  wind only            0.279       0.385      0.232       0.376
  wind+fuel            0.284       0.314      0.222       0.353
  wind+fuel+slope      0.274       0.314      0.259       0.334

Camp was run first, and the explanation it suggested -- that a fire under
35 km/h wind is wind-driven rather than fuel-limited, so a fuel term tuned for
moderate conditions adds noise -- predicts that a slow fire reverses the
ordering. Dixie's first week is that test: 10 km up the same canyon, sharing
terrain, fuel vintage and reanalysis cell, at 13 km/h instead of 35. It does
not reverse. Wind alone still wins at ~10 h, by the same margin. The regime
explanation is dead: whatever costs the fuel term IoU is not specific to a
wind-driven fire. (The second scoring pair on each fire agrees with the first;
`python -m backend.fire.validate` prints all of them.)

What Dixie does show is where the terms earn their place. At +1.7 h in that
canyon, wind+fuel+slope is the best configuration -- 0.259 against 0.232 --
and slope is what carries it, since fuel alone scores worse than no fuel at
all. Short range, steep ground, the terrain term helps.

Three things checked and ruled out:

  - Unfair calibration. Fixed; each variant gets its own R0. Wind still wins.
  - Urban treated as a hard barrier, since the Camp Fire burned through
    Paradise and 7.2% of detections land on non-burnable cells. Relaxing
    urban F_fuel from 0.0 to 0.5 moved growth-IoU by 0.001. Not the cause.
  - Fuel vintage on Dixie. LF2016 predates the 2018 and 2020 fires whose scars
    fall in that bbox, so it should overstate fuel there. Against LF2022, mean
    F_fuel inside the observed footprint is unchanged (0.527 vs 0.531). Not a
    level bias -- though 64% of individual cells disagree, which is its own
    finding: the per-cell detail a fuel term is supposed to buy is not stable
    across vintages. Some of that disagreement is Dixie itself, since LF2022
    is post-fire.

The leading remaining explanation is the calibration. F_fuel <= 1 everywhere
and averages ~0.5, so matching burned area forces R0 up two to three times
(Camp 9.8 -> 27, Dixie 22 -> 48). The fuel runs therefore drive their grass
corridors at near-full R0 while timber lags, and that spikier footprint may
score worse against a truth mask built from 375 m detection pixels than a
smooth wind ellipse does. Untested -- it needs a shape metric, not IoU.

Keep the fuel and slope terms anyway: they are what make barriers and terrain
visible in the output, and the contract's consumers need that. But do not
claim they improve accuracy on the strength of this data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from ..weather import nws
from . import firms, landfire, terrain
from .spread import (BANDS, NEIGHBOURS, R0_M_PER_MIN, arrival_times,
                     seed_from_hotspots)

CONFIGURATIONS = {
    "wind only": (False, False),
    "wind+fuel": (True, False),
    "wind+fuel+slope": (True, True),
}


def iou(predicted: np.ndarray, actual: np.ndarray) -> float:
    union = (predicted | actual).sum()
    return float((predicted & actual).sum() / union) if union else 0.0


def observed(hotspots, upto: datetime, transform, shape_) -> np.ndarray:
    """Cumulative burned footprint as of `upto`, rasterized like the seed."""
    seen = [h for h in hotspots if h.acq_time <= upto]
    return seed_from_hotspots(seen, transform, shape_) if seen else np.zeros(shape_, bool)


def _setup(seed_at: datetime, validate_at: datetime, bbox, peak_window_h: int):
    """Everything the model needs for one seed/validate pair, fetched once."""
    hotspots = firms.fetch_many(
        firms.ARCHIVE_SOURCES, bbox=bbox,
        start_date=seed_at.date() - timedelta(days=1), days=2)
    codes, profile = landfire.fetch("fuel", bbox=bbox)
    transform, shape_ = profile["transform"], codes.shape

    seed = [h for h in hotspots if h.acq_time == seed_at]
    if not seed:
        raise ValueError(f"no pass at {firms.iso(seed_at)}")

    lat, lon = (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
    gap_min = (validate_at - seed_at).total_seconds() / 60
    return {
        "ignition": seed_from_hotspots(seed, transform, shape_),
        "truth": observed(hotspots, validate_at, transform, shape_),
        "wind": nws.archived(lat, lon, seed_at, peak_window_h=peak_window_h),
        "fuel": landfire.fuel_factor(codes),
        "slope": terrain.slope_factors(landfire.fetch("slope", bbox=bbox)[0],
                                       landfire.fetch("aspect", bbox=bbox)[0],
                                       NEIGHBOURS),
        "transform": transform,
        "cell_km2": (transform.a / 1000) ** 2,
        "gap_min": gap_min,
        "band": min(BANDS, key=lambda n: abs(BANDS[n] - gap_min) if BANDS[n] else 1e9),
    }


def _predict(setup: dict, use_fuel: bool, use_slope: bool, r0: float) -> np.ndarray:
    arrival = arrival_times(
        setup["ignition"], setup["wind"].speed_kmh, setup["wind"].toward_deg,
        cell_m=setup["transform"].a,
        propensity=setup["fuel"] if use_fuel else None,
        slope=setup["slope"] if use_slope else None, r0=r0)
    return arrival <= BANDS[setup["band"]]


def calibrate(setup: dict, use_fuel: bool, use_slope: bool,
              target_km2: float, bounds=(0.5, 300.0), steps: int = 14) -> float:
    """R0 that makes this configuration burn `target_km2`, by bisection.

    Without this the ablation is meaningless: sharing one R0 across variants
    means adding F_fuel only makes the model slower, and IoU then measures
    spread rate rather than whether the fuel term puts fire in better places.
    """
    lo, hi = bounds
    for _ in range(steps):
        mid = (lo + hi) / 2
        area = _predict(setup, use_fuel, use_slope, mid).sum() * setup["cell_km2"]
        lo, hi = (mid, hi) if area < target_km2 else (lo, mid)
    return round((lo + hi) / 2, 2)


def score(seed_at: datetime, validate_at: datetime, bbox=firms.DEMO_BBOX,
          peak_window_h: int = 8, r0_by_config: dict | None = None) -> dict:
    """IoU for each model configuration, at the band closest to the real gap."""
    setup = _setup(seed_at, validate_at, bbox, peak_window_h)
    ignition, truth = setup["ignition"], setup["truth"]

    results = {}
    for label, (use_fuel, use_slope) in CONFIGURATIONS.items():
        r0 = (r0_by_config or {}).get(label, R0_M_PER_MIN)
        predicted = _predict(setup, use_fuel, use_slope, r0)
        # Growth-only IoU drops the shared seed, which otherwise inflates
        # every configuration equally and hides the differences.
        results[label] = {
            "r0": r0,
            "iou": round(iou(predicted, truth), 3),
            "iou_growth": round(iou(predicted & ~ignition, truth & ~ignition), 3),
            "predicted_km2": round(predicted.sum() * setup["cell_km2"], 1),
        }

    return {
        "seed_at": firms.iso(seed_at), "validate_at": firms.iso(validate_at),
        "gap_h": round(setup["gap_min"] / 60, 1), "band": setup["band"],
        "wind": f"{setup['wind'].speed_kmh} km/h toward {setup['wind'].toward_deg:.0f}",
        "seed_km2": round(ignition.sum() * setup["cell_km2"], 1),
        "observed_km2": round(truth.sum() * setup["cell_km2"], 1),
        "results": results,
    }


# (bbox, day to calibrate on, day to score on). The two days never overlap:
# fitting and scoring on one window would make every IoU a restatement of the
# calibration.
FIRES = {
    "camp": (firms.DEMO_BBOX, "2018-11-08", "2018-11-09"),
    # Dixie's first week, 10 km up the same canyon from Camp's origin -- near
    # enough to share terrain, fuel vintage and reanalysis cell, so the fire
    # regime is close to the only thing that differs. July at 13 km/h instead
    # of November at 35: the slow case the docstring's explanation needs.
    "dixie": ((-121.55, 39.78, -121.05, 40.10), "2021-07-15", "2021-07-16"),
}


def run(name: str, peak_window_h: int = 8) -> None:
    """Calibrate on one day, then score three seed/validate pairs on the next."""
    bbox, fit_day, score_day = FIRES[name]
    hotspots = firms.fetch_many(firms.ARCHIVE_SOURCES, bbox=bbox,
                                start_date=fit_day, days=2)
    passes = sorted({h.acq_time for h in hotspots})
    fit_passes = [p for p in passes if p.date().isoformat() == fit_day]
    score_passes = [p for p in passes if p.date().isoformat() == score_day]

    fit = _setup(fit_passes[0], fit_passes[2], bbox, peak_window_h)
    target = fit["truth"].sum() * fit["cell_km2"]
    print(f"{name.upper()}: calibrating on {firms.iso(fit_passes[0])} -> "
          f"{firms.iso(fit_passes[2])} (+{fit['gap_min'] / 60:.1f} h), "
          f"target {target:.1f} km2")

    r0 = {}
    for label, (use_fuel, use_slope) in CONFIGURATIONS.items():
        r0[label] = calibrate(fit, use_fuel, use_slope, target)
        print(f"  {label:<18} R0 = {r0[label]:>6} m/min")

    for seed_at, validate_at in [(score_passes[0], score_passes[2]),
                                 (score_passes[0], score_passes[3]),
                                 (score_passes[1], score_passes[4])]:
        report = score(seed_at, validate_at, bbox=bbox,
                       peak_window_h=peak_window_h, r0_by_config=r0)
        print()
        print(f"seed {report['seed_at']} -> validate {report['validate_at']} "
              f"(+{report['gap_h']} h, scored on {report['band']})")
        print(f"  wind {report['wind']} | seed {report['seed_km2']} km2 "
              f"-> observed {report['observed_km2']} km2")
        print(f"  {'configuration':<18}{'R0':>7}{'IoU':>8}{'IoU growth':>13}{'pred km2':>11}")
        for label, row in report["results"].items():
            print(f"  {label:<18}{row['r0']:>7}{row['iou']:>8}"
                  f"{row['iou_growth']:>13}{row['predicted_km2']:>11}")


if __name__ == "__main__":
    import sys

    for name in [a for a in sys.argv[1:] if a in FIRES] or list(FIRES):
        run(name)
        print()
