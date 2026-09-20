"""MAGI: three spread models deliberate, and the ensemble is the answer.

Named for Evangelion's three supercomputers because they do the same job here.
One model draws one line on a map with no error bar, which is the least honest
thing a fire model can hand an evacuation planner. Three models with different
dispositions give a core all of them agree on and a fringe only the pessimist
claims.

That gap is MODEL DISAGREEMENT, and it is not a forecast confidence interval.
Three settings of one kernel sharing a seed, a wind field, a grid and a solver
can only disagree about the things they were set up to disagree about; nothing
here is calibrated against observed outcome frequency, so "the fire stays
inside CONFIRMED x% of the time" is not a statement this file can support.
`rothermel.py` exists because an independent kernel is what the spread would
need to mean more than that. Say "the models disagree beyond here", not
"we are 90% sure".

The dispositions are not flavour -- each is a documented uncertainty in the
inputs this engine already knows about:

  MELCHIOR-1   the scientist. The calibrated model as fitted: wind, fuel, slope.
  BALTHASAR-2  the mother. Protective. ERA5 reanalysis is ~25 km and smooths
               the Jarbo Gap gusts away (see weather/nws.archived), so this one
               runs the wind the RAWS stations actually recorded and a fire
               faster than an R0 fitted to an already-slowing burn.
  CASPER-3     the sceptic. Keeps the barriers, throws away the tuning: water
               and bare rock are about as close to measurement as this engine
               gets, while 0.2-vs-0.7 is a heuristic laid over a 2016 guess at
               vegetation. No slope term either.

Balthasar only ever arrives sooner than Melchior, so it can never be the
slowest of the three: CONFIRMED is exactly Melchior-and-Casper, and Balthasar's
vote lands on MAJORITY instead, where it is the median on 64% of the 13.6k cells
all three reach. Giving it a wind veer as well as a gust, so that it could
disagree about direction and constrain unanimity too, moved that share by two
points and the advisory footprint by -2 km2, so the knob is not in here.

Consensus is an order statistic, not a vote loop. Sort the three arrival times
per cell: the soonest is when the first model says fire is there (ADVISORY),
the middle is when two of three agree (MAJORITY -- the MAGI's decision, and
what ships in the contract), the latest is unanimity (CONFIRMED). Sorting is
monotone, so CONFIRMED subset MAJORITY subset ADVISORY by construction, the
same way bands_to_geojson gets h1 subset h3 subset h6 for free. That holds
exactly on the grids; once each level is closed and simplified into its own
polygons the rings overlap by about 1.5e-5 of their area, which the tests pin
as a tolerance rather than paying geometry plumbing to remove.

RESULT, recorded the same way validate.py records its negative one: the majority
does NOT score better than the best single model, on either validation fire.
Growth-only IoU, same fires and scoring days as the ablation, so the two tables
are comparable:

                        Camp 2018-11-09       Dixie 2021-07-16
                      +1.7 h     +11.4 h     +1.7 h     +10.5 h
  MELCHIOR-1           0.136       0.272      0.064       0.272
  BALTHASAR-2          0.243       0.293      0.126       0.355
  CASPER-3             0.231       0.361      0.101       0.289
  ADVISORY             0.268       0.299      0.146       0.359
  MAJORITY             0.208       0.339      0.091       0.303
  CONFIRMED            0.130       0.284      0.053       0.250

MAJORITY loses in all four windows, and ADVISORY -- the widest band, the one a
lone dissenter is enough to draw -- wins three. Before reading that as a reason
to ship ADVISORY: at +1.7 h on both fires the ranking is exactly the ranking of
predicted area, biggest first, from CONFIRMED at the bottom to ADVISORY at the
top. The truth mask is FIRMS detections, and a cell that burned and cooled stops
being reported (validate.py's caveat), so at short range this metric rewards
size and cannot tell an ensemble anything.

The one window where shape beats size is Camp at +11.4 h. CASPER-3 predicts less
than MAJORITY, BALTHASAR-2 and ADVISORY and still beats all three at 0.361,
which is the ablation's wind-alone result showing up in the ensemble.

Making CASPER-3 respect the non-burnable zeros rather than ignoring fuel
entirely cost it 0.018 growth-IoU at +1.7 h and 0.003 at +11.4 h on Camp, and
removed 26 km2 of 11.4 h footprint (6 km2 at +1.7 h) that sat on water or bare
rock. Kept: a fringe drawn across a reservoir is not an honest advisory.

Where CASPER-3 is known to be wrong is short range on steep ground -- Dixie at
+1.7 h is validate.py's one positive result for the derived terms, and slope is
what carries it. The sceptic drops slope anyway, because dissent is its job and
the ablation's long-range result is its warrant. That disagreement is what the
ADVISORY-to-CONFIRMED gap is for.

So the ensemble is kept for the uncertainty band, not for accuracy: MAJORITY is
the median of three, which is steadier than any one model when the inputs are
wrong in unknown directions, and that gap is the only error bar this engine can
honestly draw. The doctrines are deliberately NOT re-tuned to win the table
above; that would be fitting three models to two fires, which is the mistake
validate.py exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from . import contract, firms, spread, validate
from .firms import DEMO_BBOX
from .spread import BANDS, R0_M_PER_MIN, arrival_times, bands_to_geojson


@dataclass(frozen=True)
class Magus:
    name: str
    doctrine: str
    wind_gain: float = 1.0
    r0_gain: float = 1.0
    use_fuel: bool = True  # False keeps the barriers, drops the weighting
    use_slope: bool = True


MAGI = (
    Magus("MELCHIOR-1", "calibrated physics: wind, fuel and slope as fitted"),
    Magus("BALTHASAR-2", "protective: the gusts the reanalysis smoothed away",
          wind_gain=1.8, r0_gain=1.25),
    Magus("CASPER-3", "sceptical: barriers yes, fuel weighting and slope no",
          r0_gain=0.8, use_fuel=False, use_slope=False),
)

# Level k is "k of the three agree". Ordered widest first, which is also the
# order np.sort puts the arrival times in.
LEVELS = ("advisory", "majority", "confirmed")

DECISION = "majority"  # 2 of 3: dropping a lone dissenter is the whole point


def deliberate(scene: spread.Scene) -> dict[str, np.ndarray]:
    """One arrival-time grid per magus, all from the same observations.

    `use_fuel=False` is not validate.py's wind-only config: it keeps the
    non-burnable zeros and flattens the rest to 1.0. Water and bare rock are
    about as close to a measurement as this engine gets, while 0.2-vs-0.7 is a
    heuristic over a 2016 vegetation guess -- and a model with no barriers at
    all draws an advisory fringe straight across a reservoir.
    """
    return {
        magus.name: arrival_times(
            scene.ignition, scene.wind.speed_kmh * magus.wind_gain,
            scene.wind.toward_deg, cell_m=scene.cell_m,
            propensity=(scene.propensity if magus.use_fuel
                        else (scene.propensity > 0).astype("float32")),
            slope=scene.slope if magus.use_slope else None,
            r0=R0_M_PER_MIN * magus.r0_gain,
            convergence_deg=scene.convergence)
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

    The comparable measure: every model and level is counted the same way, so
    CONFIRMED <= each model <= ADVISORY holds exactly. The polygon areas under
    `confidence` run about 5% higher on the replay fire, because the closing that
    makes the rings drawable also fills their pinholes -- never mix the two in
    one table.
    """
    return {name: round(float((arrival <= minutes).sum()) * cell_m ** 2 / 1e6, 1)
            for name, minutes in BANDS.items()}


def _verdict(areas: dict[str, dict[str, float]]) -> str:
    """One line about the 6 h footprint for the chat model to read out."""
    return (f"All three models agree on {areas['confirmed']['h6']} km2 of the 6 h "
            f"footprint, two of three on {areas['majority']['h6']} km2, and one "
            f"alone extends it to {areas['advisory']['h6']} km2.")


def risk_payload(bbox=DEMO_BBOX, when: datetime | None = None,
                 peak_window_h: int = 8) -> dict:
    """The contract, decided by 2 of 3, plus the MAGI's own reasoning.

    Same name and shape as spread.risk_payload, so an endpoint swaps one import
    and nothing downstream has to know an ensemble ran. The disagreement lives
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
        # Models and levels together, all raster-counted so the six rows compare.
        "area_km2": {name: _raster_areas(arrival, scene.cell_m)
                     for name, arrival in {**arrivals, **levels}.items()},
        "confidence": {level: {"risk_polygons": band["risk_polygons"],
                               "area_km2": band["area_km2"]}
                       for level, band in bands.items()},
    }
    payload["summary"]["magi_verdict"] = _verdict(
        {level: band["area_km2"] for level, band in bands.items()})
    # Same guard spread.risk_payload has. assemble() deliberately has none, and
    # this function is advertised as a drop-in, so the check belongs here too.
    for level, band in payload["magi"]["confidence"].items():
        contract.check({**payload, "risk_polygons": band["risk_polygons"],
                        "summary": {**payload["summary"],
                                    "area_km2": band["area_km2"]}})
    return contract.check(payload)


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
        # codes feed assemble's dominant_fuels, which scoring never reaches.
        ignition=setup["ignition"], codes=np.empty(0, dtype="int16"),
        propensity=setup["fuel"], slope=setup["slope"],
        transform=setup["transform"], wind=setup["wind"], seed=[],
        seed_time=seed_at)

    arrivals = deliberate(scene)
    grids = {**arrivals, **consensus(arrivals)}
    truth, ignition = setup["truth"], setup["ignition"]
    # The window's real elapsed time. Scoring at BANDS[band] instead meant a
    # 12 h observation gap was compared against a 6 h simulation -- see
    # validate._predict, which had the same defect.
    minutes = setup["horizon_min"]

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
        # Same fires and the same scoring day as validate.FIRES, so the ensemble
        # is answerable to the ablation's evidence rather than its own window.
        for fire, (bbox, _, score_day) in validate.FIRES.items():
            hotspots = firms.fetch_many(firms.ARCHIVE_SOURCES, bbox=bbox,
                                        start_date=score_day, days=1)
            passes = sorted({h.acq_time for h in hotspots})
            pairs = [(passes[0], passes[2])]
            if len(passes) > 4:
                pairs.append((passes[1], passes[4]))
            for seed_at, validate_at in pairs:
                report = score(seed_at, validate_at, bbox=bbox)
                print(f"{fire}: seed {report['seed_at']} -> "
                      f"{report['validate_at']} (+{report['gap_h']} h, "
                      f"{report['band']}), observed {report['observed_km2']} km2")
                print(f"  {'':<14}{'IoU':>7}{'IoU growth':>13}{'km2':>9}")
                for name, row in report["results"].items():
                    print(f"  {name:<14}{row['iou']:>7}{row['iou_growth']:>13}"
                          f"{row['km2']:>9}")
                print()
        sys.exit()

    payload = risk_payload(when=None if "--live" in sys.argv else start)
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
        area = magi["area_km2"][level]
        mark = "  <-- DECISION" if level == magi["decision"] else ""
        print(f"  {level.upper():<12} {area['h1']:>6} {area['h3']:>6} "
              f"{area['h6']:>6}{mark}   drawn as "
              f"{confidence[level]['area_km2']['h6']} km2 of polygon")
    print(f"\n  {payload['summary']['magi_verdict']}")

    if "--write" in sys.argv:
        out = Path(__file__).resolve().parents[2] / "demo_data" / "risk_magi.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {out} ({out.stat().st_size / 1024:.0f} KB)")
