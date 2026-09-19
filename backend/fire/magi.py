"""MAGI: three spread models deliberate, and the ensemble is the answer.

Named for Evangelion's three supercomputers because they do the same job here.
One model draws one line on a map with no error bar, which is the least honest
thing a fire model can hand an evacuation planner. Three models with different
dispositions give a core all of them agree on and a fringe only the pessimist
claims, and that gap *is* the forecast uncertainty.

The dispositions are not flavour -- each is a documented uncertainty in the
inputs this engine already knows about:

  MELCHIOR-1   the scientist. The calibrated model as fitted: wind, fuel, slope.
  BALTHASAR-2  the mother. Protective. ERA5 reanalysis is ~25 km and smooths
               the Jarbo Gap gusts away (see weather/nws.archived), so this one
               runs the wind the RAWS stations actually recorded, and a fire
               faster than an R0 fitted to an already-slowing burn.
  CASPER-3     the sceptic. Trusts the satellite and the anemometer and nothing
               derived: no LANDFIRE fuel model (2016 vintage, and a fuel code
               is a guess about vegetation, not a measurement), no slope term.

Consensus is an order statistic, not a vote loop. Sort the three arrival times
per cell: the soonest is when the first model says fire is there (ADVISORY),
the middle is when two of three agree (MAJORITY -- the MAGI's decision, and
what ships in the contract), the latest is unanimity (CONFIRMED). Sorting is
monotone, so CONFIRMED subset MAJORITY subset ADVISORY by construction, the
same way bands_to_geojson gets h1 subset h3 subset h6 for free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from . import firms, landfire, spread, validate
from .firms import DEMO_BBOX
from .spread import BANDS, R0_M_PER_MIN, arrival_times, bands_to_geojson


@dataclass(frozen=True)
class Magus:
    name: str
    doctrine: str
    wind_gain: float = 1.0
    r0_gain: float = 1.0
    use_fuel: bool = True
    use_slope: bool = True


MAGI = (
    Magus("MELCHIOR-1", "calibrated physics: wind, fuel and slope as fitted"),
    Magus("BALTHASAR-2", "protective: the gusts the reanalysis smoothed away",
          wind_gain=1.8, r0_gain=1.25),
    Magus("CASPER-3", "sceptical: satellite and wind only, nothing derived",
          r0_gain=0.8, use_fuel=False, use_slope=False),
)

# Level k is "k of the three agree". Ordered widest first, which is also the
# order np.sort puts the arrival times in.
LEVELS = ("advisory", "majority", "confirmed")

DECISION = "majority"  # 2 of 3: dropping a lone dissenter is the whole point


def deliberate(scene: spread.Scene) -> dict[str, np.ndarray]:
    """One arrival-time grid per magus, all from the same observations."""
    return {
        magus.name: arrival_times(
            scene.ignition, scene.wind.speed_kmh * magus.wind_gain,
            scene.wind.toward_deg, cell_m=scene.cell_m,
            propensity=scene.propensity if magus.use_fuel else None,
            slope=scene.slope if magus.use_slope else None,
            r0=R0_M_PER_MIN * magus.r0_gain)
        for magus in MAGI
    }


def consensus(arrivals: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Arrival time per level of agreement: the k-th soonest of the three.

    `arrival <= t` is weakest for the soonest grid, so the levels nest without
    anyone having to intersect polygons afterwards.
    """
    assert len(arrivals) == len(LEVELS), "LEVELS names three models, not more"
    ranked = np.sort(np.stack(list(arrivals.values())), axis=0)
    return dict(zip(LEVELS, ranked))


def _raster_areas(arrival: np.ndarray, cell_m: float) -> dict[str, float]:
    """Burned area per band counted straight off the grid.

    Cheaper than polygonizing and only used for the per-model diagnostics, so
    it skips the closing and simplify that make the shipped polygons drawable
    -- expect it to read a little under the matching `area_km2`.
    """
    return {name: round(float((arrival <= minutes).sum()) * cell_m ** 2 / 1e6, 1)
            for name, minutes in BANDS.items()}


def _verdict(areas: dict[str, dict[str, float]]) -> str:
    """One line about the 6 h footprint for the chat model to read out."""
    return (f"All three models agree on {areas['confirmed']['h6']} km2 of the 6 h "
            f"footprint, two of three on {areas['majority']['h6']} km2, and one "
            f"alone extends it to {areas['advisory']['h6']} km2.")


def magi_payload(bbox=DEMO_BBOX, when: datetime | None = None,
                 peak_window_h: int = 8) -> dict:
    """The contract, decided by 2 of 3, plus the MAGI's own reasoning.

    `risk_polygons` and `summary` are exactly the shape risk_payload returns,
    so nothing downstream has to know an ensemble ran. The disagreement lives
    under `magi`, where the map can draw the advisory fringe if it wants to.
    """
    scene = spread.gather(bbox=bbox, when=when, peak_window_h=peak_window_h)
    arrivals = deliberate(scene)
    levels = consensus(arrivals)
    bands = {level: bands_to_geojson(arrival, scene.transform)
             for level, arrival in levels.items()}

    payload = spread.assemble(scene, bands[DECISION], levels[DECISION])
    payload["magi"] = {
        "decision": DECISION,
        "doctrine": {magus.name: magus.doctrine for magus in MAGI},
        "area_km2": {name: _raster_areas(arrival, scene.cell_m)
                     for name, arrival in arrivals.items()},
        "confidence": {level: {"risk_polygons": band["risk_polygons"],
                               "area_km2": band["area_km2"]}
                       for level, band in bands.items()},
    }
    payload["summary"]["magi_verdict"] = _verdict(
        {level: band["area_km2"] for level, band in bands.items()})
    return payload


def score(seed_at: datetime, validate_at: datetime, bbox=DEMO_BBOX,
          peak_window_h: int = 8) -> dict:
    """Each magus and each consensus level, IoU'd against what the fire did.

    Reuses validate's setup so this is scored the same way the ablation is:
    ground truth is the FIRMS footprint up to `validate_at`, and growth-IoU
    drops the shared seed. The levels differ in area by design, so they trade
    precision against recall -- the number that matters is whether MAJORITY
    beats every single model, not whether ADVISORY has the best recall.
    """
    setup = validate._setup(seed_at, validate_at, bbox, peak_window_h)
    scene = spread.Scene(
        ignition=setup["ignition"], codes=landfire.fetch("fuel", bbox=bbox)[0],
        propensity=setup["fuel"], slope=setup["slope"],
        transform=setup["transform"], wind=setup["wind"], seed=[],
        seed_time=seed_at)

    arrivals = deliberate(scene)
    grids = {**arrivals, **consensus(arrivals)}
    truth, ignition = setup["truth"], setup["ignition"]
    minutes = BANDS[setup["band"]]

    rows = {}
    for name, arrival in grids.items():
        burned = arrival <= minutes
        rows[name] = {
            "iou": round(validate.iou(burned, truth), 3),
            "iou_growth": round(validate.iou(burned & ~ignition,
                                            truth & ~ignition), 3),
            "km2": round(float(burned.sum()) * setup["cell_km2"], 1),
        }
    return {"seed_at": firms.iso(seed_at), "validate_at": firms.iso(validate_at),
            "gap_h": round(setup["gap_min"] / 60, 1), "band": setup["band"],
            "observed_km2": round(float(truth.sum()) * setup["cell_km2"], 1),
            "results": rows}


if __name__ == "__main__":
    import json
    import sys
    from datetime import timezone
    from pathlib import Path

    start = datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)

    if "--score" in sys.argv:
        hotspots = firms.fetch_many(firms.ARCHIVE_SOURCES,
                                    start_date="2018-11-09", days=1)
        passes = sorted({h.acq_time for h in hotspots})
        for seed_at, validate_at in [(passes[0], passes[2]), (passes[1], passes[4])]:
            report = score(seed_at, validate_at)
            print(f"seed {report['seed_at']} -> {report['validate_at']} "
                  f"(+{report['gap_h']} h, {report['band']}), observed "
                  f"{report['observed_km2']} km2")
            print(f"  {'':<14}{'IoU':>7}{'IoU growth':>13}{'km2':>9}")
            for name, row in report["results"].items():
                print(f"  {name:<14}{row['iou']:>7}{row['iou_growth']:>13}"
                      f"{row['km2']:>9}")
            print()
        sys.exit()

    payload = magi_payload(when=None if "--live" in sys.argv else start)
    magi, confidence = payload["magi"], payload["magi"]["confidence"]

    print(f"MAGI SYSTEM  --  hotspots {payload['data_as_of']['firms']}, "
          f"wind {payload['summary']['wind_speed_kmh']} km/h toward "
          f"{payload['summary']['primary_spread_direction']}")
    print("  h1 / h3 / h6 km2")
    for magus in MAGI:
        area = magi["area_km2"][magus.name]
        print(f"  {magus.name:<12} {area['h1']:>6} {area['h3']:>6} {area['h6']:>6}"
              f"   {magus.doctrine}")
    print()
    for level in reversed(LEVELS):
        area = confidence[level]["area_km2"]
        mark = "  <-- DECISION" if level == magi["decision"] else ""
        print(f"  {level.upper():<12} {area['h1']:>6} {area['h3']:>6} "
              f"{area['h6']:>6}{mark}")
    print(f"\n  {payload['summary']['magi_verdict']}")

    if "--write" in sys.argv:
        out = Path(__file__).resolve().parents[2] / "demo_data" / "risk_magi.json"
        out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        print(f"\nwrote {out} ({out.stat().st_size / 1024:.0f} KB)")
