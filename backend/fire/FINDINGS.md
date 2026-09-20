# Fire engine: what the experiments settled

What a new session needs before touching the model: which questions are
already answered, so nobody re-runs a dead end. `AGENTS.md` is the rules,
this is the evidence. All nine milestones from the role brief are done, and
merged to `main`; the engine runs live or in replay against real FIRMS,
GOES, LANDFIRE, HRRR and ERA5 data.

Detail lives in commit messages and in `validate.py`'s docstring. This file
points at it rather than restating it, so the two can't drift. A session log at
the end summarises every work block on the branch, including the MAGI ensemble
track that ran in parallel.

## The ablation

`./.venv/Scripts/python.exe -m backend.fire.validate` scores wind-only against wind+fuel and
wind+fuel+slope, on two fires, each variant calibrated separately. Growth-only
IoU:

```
                        Camp 2018-11-09       Dixie 2021-07-16
                      +1.7 h     +11.4 h     +1.7 h     +10.5 h
  wind only            0.279       0.385      0.232       0.376
  wind+fuel            0.284       0.314      0.222       0.353
  wind+fuel+slope      0.274       0.314      0.259       0.334
```

- **Fuel and slope do not improve IoU on either fire.** Wind alone wins at the
  ~10 h horizon on both. Say so openly; do not claim otherwise in the pitch.
- **The regime explanation is dead.** Camp suggested the terms lose because a
  35 km/h fire is wind-driven rather than fuel-limited. Dixie's first week
  tested exactly that -- same canyon 10 km upriver, sharing terrain, fuel
  vintage and ERA5 cell, at 13 km/h instead of 35 -- and the ordering did not
  reverse. Whatever costs the fuel term IoU is not regime-specific.
- **Slope earns its place at short range in steep ground.** Dixie +1.7 h is the
  one case the full model wins (0.259 vs 0.232), and slope carries it: fuel
  alone scores worse than no fuel.
- **Already ruled out:** unfair calibration (each variant gets its own R0),
  urban as a hard barrier (moved IoU by 0.001), and fuel vintage on Dixie
  (mean F_fuel 0.527 LF2016 vs 0.531 LF2022 inside the observed footprint,
  though 64% of individual cells disagree).
- **Leading untested suspect:** calibration. `F_fuel <= 1` averaging ~0.5 forces
  R0 up 2-3x (Camp 9.8 -> 27, Dixie 22 -> 48), so fuel runs drive grass
  corridors at near-full rate while timber lags. A spikier footprint may score
  worse against a 375 m detection mask than a smooth wind ellipse. Testing it
  needs a shape metric, not IoU.

Keep the fuel and slope terms regardless: they are what make barriers and
terrain visible, which the contract's consumers need.

## Palisades 2025: against the standard model, and against the fire

`./.venv/Scripts/python.exe -m backend.fire.palisades`. Four windows over the
fire's first three days, R0 fitted once on the first and held for the other
three. The comparator is `elliptical.py`, the Alexander/Finney ellipse FARSITE
and the commercial tools built on it use, run through this engine's own solver
on the same seed, wind and grid so the wind shape is the only difference.
Growth IoU:

```
                            01-07 21:27Z  01-08 09:49Z  01-08 21:08Z  01-09 09:30Z
                                +12.0 h      +10.9 h       +12.0 h       +10.9 h
                               (fitted)     (held out)    (held out)    (held out)
  Ignis, wind^3 + fuel + slope   0.456        0.119         0.347         0.365
  FARSITE-class ellipse          0.417        0.105         0.326         0.341
  FARSITE-class, no fuel/slope   0.182        0.088         0.331         0.349
```

**These numbers replace an earlier three-window table, and they are not a
re-run of the same measurement.** `validate._setup` fetched a fixed two-day
FIRMS span starting the day before the seed pass, so any window whose
validation pass fell on the *next* UTC day never saw it: truth stopped at the
seed pass and the model was scored against the fire's past. Two of the three
windows, including the calibration one, were affected -- the fit window's
truth was 13.4 km2 when the real footprint at 09:26Z was 72.0. The span is now
derived from `validate_at`. Camp and Dixie are same-day windows and are
unchanged by the fix, so the ablation table above still stands.

- **Ignis edges the standard ellipse on every window**, by 0.014 to 0.039
  growth IoU. Consistent in direction across four windows, but small, and
  three of the four are within the spread you would expect from a different
  choice of overpass. It is not evidence that the cubic wind term is better;
  it is evidence the two are close.
- **The fuel and slope terms do not carry the signal the old table showed.**
  Stripping them costs 0.27 on the fit window and 0.03 on window 2, but on
  windows 3 and 4 the stripped model is *ahead* of the full ellipse
  (0.331 vs 0.326, 0.349 vs 0.341). The earlier claim that Palisades was the
  first fire where the terms bought accuracy was an artifact of the truncated
  truth. It goes back to matching Camp and Dixie: the terms buy legibility,
  not IoU.
- **Every model over-predicts area by roughly 2x on the held-out windows**,
  174-235 km2 against 86-100 km2 observed. R0 is fitted to the first night, a
  29 km/h window, and windows 2 and 3 blew 36-37. A single fitted R0 does not
  transfer across a change in wind regime -- the calibration weakness
  `spread.py` warns about in its R0 comment, now measured in the other
  direction from before. Note the over-prediction is partly the truth mask:
  detections only show actively burning pixels, so observed area is a floor.
- **Window 2 is the weak one, at 0.119.** Its seed already covers 69 km2 of
  the 86 km2 eventually observed, so there is very little growth left to get
  right and growth IoU has almost nothing to divide by. Reported at the same
  size as the rest, in the figure and in the UI.
- **No comparison against an actual commercial prediction is possible.**
  Technosylva, Wildfire Analyst and the rest run under contract and publish no
  polygons for historical fires. `palisades.py` says this in its docstring, and
  the figure says it on its face, because "FARSITE-class" invites exactly the
  misreading that it is somebody's product.

The figure is `demo_data/palisades_comparison.png`, regenerated by that
command. `--json` instead writes `demo_data/palisades_replay.json`, the same
four windows as GeoJSON for the frontend's stepped replay tab. Ground truth is
the FIRMS footprint at the validation pass, with the NIFC final perimeter
(23,448 acres, three weeks) drawn only for context.

## Observation latency, measured on a live fire

Run on a Sierra fire at 2026-09-19T20:03Z, bbox `(-119.90, 37.40, -119.30, 37.85)`.
The newest VIIRS pass over it was **09:30, 09:49 and 11:10Z** -- three passes,
all morning, and the 11:10 one was the smallest of the three. The engine
seeded from a nine-hour-old footprint and labelled the projection "h6". NWS
gridpoint wind read 13:00Z at 20:03Z, because `values[0]` of a gridpoint
series is the issuance boundary and not the current hour.

Latency, not the spread physics, was the largest error term in a live payload.
The ablation above moves IoU by hundredths; this moves the seed by nine hours.

GOES ABI (`goes.py`) and HRRR (`nws.live`) close it. Same bbox, same wind,
GOES seed on and off:

```
                seed                     n    current    h1     h3     h6   growth
  VIIRS only    2026-09-19T11:10:00Z    23      9.0     10.3   13.8   17.5   +94%
  VIIRS + GOES  2026-09-19T20:06:17Z    27     33.5     34.3   38.2   45.1   +35%
```

- **Seed age 9 h -> 5 min, weather 7 h -> 11 min.** That is the win, and it is
  the only one claimed here.
- **Most of the area jump is resolution smear, not new fire.** Distance from
  each ABI pixel to the nearest detection in that VIIRS pass: 0.20, 0.51, 0.69
  and **2.79 km**. Three confirm ground VIIRS already had. One is real new
  fire, ~2.8 km beyond the morning footprint, which is ~0.3 km/h over the nine
  hours and plausible for this fire.
- So `PIXEL_M = 3000` over-warns: 24 km2 of the 33.5 is a kilometres-wide cell
  drawn around ground that was already inside the footprint. Conservative for
  an evacuation map, wrong as an area estimate. It is one constant in
  `goes.py`; the file also carries a per-pixel `Area` if the edge ever needs
  to be better than a single number.
- **The wind direction flipped**, 270 (toward west) to 86 (toward east), which
  is the difference between evacuating the right side of a fire and the wrong
  one. Almost all of that is the seven hours, not the model: a stale morning
  forecast against an afternoon upslope reversal in a Sierra canyon.

Not measured: whether GOES seeding improves IoU. It cannot be tested the way
the ablation above was -- the SP archive lags NRT by two months, so a replay
fire has no latency to remove. Doing it honestly means replaying GOES frames
from the same archive, which is a separate piece of work.

## Rothermel, and what its validation does and does not cover

`rothermel.py` is the Rothermel 1972 / Albini 1976 surface spread model, added
to give the MAGI ensemble a member that is not a reparameterization of
`spread.py`. It exists because the three magi share one kernel, which is why
the ensemble has never beaten its best member -- correlated members cannot
draw an error bar. It also has **no fitted R0**, which is the failure the
Palisades windows above measured.

Pyretechnics was the first choice and cannot be installed here: it wants
Python ~=3.11 against this venv's 3.12.6, numpy ~=1.26.2 against 2.5.3,
rasterio ~=1.4.3 against 1.5.1, and builds from a Cython sdist. Porting the
equations was cheaper than migrating a venv two other people are working in.

### Validated

- **Every fuel model parameter, against the primary source.** All 40 Scott &
  Burgan models' 1-hr, 10-hr, 100-hr, live herbaceous and live woody loads,
  all three SAV ratios, bed depth and dead extinction moisture were compared
  value by value against RMRS-GTR-153 table 7. All match.
- **One real bug, found that way.** `HEAT_CONTENT` was hardcoded at 8000
  Btu/lb with a comment asserting every model used it. **GR6 is 9000**, alone
  in the set. Now `HEAT_CONTENT_BY_MODEL`, and pinned by a test.
- **Characteristic SAV and packing ratio, against the published per-model
  pages.** 39 of the 40 agree to 0.0-0.1%. This is the check that matters for
  the implementation rather than the inputs: it exercises the surface-area
  weighting and the dynamic curing transfer.
- **Equation forms, against RMRS-GTR-371.** Q_ig, epsilon, the C/B/E wind
  coefficients, the moisture and mineral damping coefficients, propagating
  flux ratio, packing ratio and net fuel load all read back verbatim.

### The one disagreement, left standing

GS4 computes to a characteristic SAV of 1631 against the 1674 its GTR-153 page
publishes, a 2.6% gap. Characteristic SAV telescopes to
`sum(sigma^2 w) / sum(sigma w)`, which is invariant to how load is split
between the dead and live categories, so curing cannot explain it; the packing
ratio and fine fuel load on that same page both agree with our loads, which
rules the loads out. No value of the live woody SAV in the published set
reproduces 1674 either. Recorded as a known difference and pinned by a test.
Bending one model's inputs to hit one published number is the kind of fit
`validate.py` exists to catch.

### Spread rates, against the BehavePlus core

Done, and it found two bugs. BehavePlus itself is a Windows GUI application,
but its computational core ships as `pyrothermel` on PyPI with a cp312
Windows wheel -- the actual Behave C++ engine, callable from Python. Installed
to a scratchpad with `pip --target`, never into `.venv`.

All 40 models were run through both at matched midflame wind, matched
moisture and zero slope. Starting point: **this module was 0.43-0.72x the
reference**, median 0.495.

- **Bug 1: three size-class bins instead of six.** Net fuel loading bins by
  SAV, and the 10-hr and 100-hr classes were sharing a bin, so they shared a
  weight. That over-weights coarse fuels: up to +73% on the litter models with
  the heaviest 100-hr loads (TL4, TL7, SB1), while the 1-hr-dominated models
  (TL8, TL9, SB3) were untouched -- which is how it stayed hidden. Six bins
  cut the spread of disagreement from 0.39-0.72 to 0.39-0.49.
- **Bug 2: curing was a free parameter.** It defaulted to 1.0, moving every
  blade of grass into the dead pool at 6% moisture, and ran the grass models
  up to 60% fast. It is now derived from live herbaceous moisture the way the
  reference does it: green at 120%, fully cured at 30%, linear between. One
  fewer knob.
- **The mineral damping coefficient is deliberately not applied.** Rothermel
  gives eta_s = 0.174 S_e^-0.19, which is 0.4174 at S_e = 0.01 -- a factor of
  2.4 on reaction intensity. The reference does not appear to apply it, and
  the arithmetic says the reference is right: reproducing its reaction
  intensity for TL8 while keeping the coefficient demands a net fuel load of
  0.578 lb/ft2, and TL8's whole oven-dry load is 0.381. No net loading can
  exceed the load it comes from. Gamma' was checked two ways (imperial, and
  GTR-371's metric reformulation) and is not the culprit. Unresolved between
  the published equation and the reference implementation; matching the
  implementation people actually fight fires with is the defensible side.

**After the fixes: every one of the 40 models agrees with the BehavePlus core
to a constant 1.029, range 1.028-1.030.** Independent of wind speed, so the
residual sits in the no-wind rate rather than the wind factor. Bulk density,
characteristic SAV and packing ratio all match the reference exactly, so it is
a single unidentified scalar rather than a structural difference. 2.9% is well
inside the model's own uncertainty, and being constant it cancels out of every
relative comparison -- which is all the ensemble asks of it. Pinned by a test
so it cannot drift silently.

Still worth knowing: agreement with BehavePlus is not agreement with a fire.
This validates the implementation, not the physics.

## Ground truth, and why the absolute numbers are low

Truth is the union of FIRMS detections up to the validation time, not a NIFC
perimeter. A detection is an *actively burning* pixel, so cells that burned and
cooled drop out and the observed footprint understates burned area. Absolute
IoU is therefore pessimistic; the ablation is the honest comparison because the
bias applies to every configuration equally.

## Open, deliberately not started

- **`contracts/` is still empty**, though `AGENTS.md` and `demo_data/README.md`
  both point teammates at it. `backend/fire/contract.py` is the checkable
  version, proposed for that directory once the team agrees -- shared, so not
  moved unilaterally.
- **GOES seeding is not validated against IoU**, for the reason above. The
  `PIXEL_M` constant is the open knob.
- **No HTTP endpoint exists** anywhere in the repo. The brief asks for one, but
  the backend teammate may want to own the app entry point, so ask first.
  `risk_payload()` also refetches everything per call; an endpoint needs a TTL
  cache to be usable live.

## Session log

Grouped from commit history, oldest first. Two sessions ran in parallel on
2026-09-19 -- the model/validation track and the MAGI ensemble track -- which is
why `magi.py` appears inside a milestone-9 commit that used `git add -A`. If a
file's history looks like someone else touched it mid-change, that is why.

| work | commits | what it settled |
|---|---|---|
| scaffold | `75844f7`, `8cae7a7` | Python 3.12 venv, pinned geospatial deps, agent rules. A hand-drawn `demo_data/risk_demo.json` shipped first so the routing and map teammates were never blocked on the real model. |
| data layers | `bd3d182`, `2bb78d9` | FIRMS hotspots, live NRT and SP archive, disk-cached. LANDFIRE fuel clipped and resampled by the image service, so no national raster is ever downloaded. |
| the model | `9ff6c01`, `dd07103`, `6ce93ed` | Arrival-time Dijkstra rather than a stepped automaton, so the bands nest by construction. Then the full contract payload with wind and fuel, then directional F_slope. |
| replay | `c51f5a0` | T0/+1h/+3h/+6h frames, each re-seeded from whatever satellite pass was newest at that hour, so the demo shows observation staleness and not just fire growth. |
| validation | `a7acf52` | IoU against the FIRMS footprint, each variant calibrated separately. Negative result: fuel and slope do not improve IoU on the Camp Fire. |
| overlay | `40bcb40` | `demo_data/fuel_overlay.png` for the map. Also swept in the first `magi.py` from the parallel session. |
| second fire | `067c9b0` | Dixie's first week tested the regime explanation and killed it. One positive result: slope earns its place at short range on steep ground. |
| contract | `36281b2` | `contract.py`. Lon/lat order and cumulative nesting are geometric, so no JSON schema expresses them. `spread.risk_payload()` now returns through `check()`. |
| docs | `509d4ba`..`11b996a` | `README.md` is orientation and commands, this file is the evidence, `AGENTS.md` is the rules. |
| MAGI ensemble | `6f1a812` | `magi.py` and `tests/test_magi.py`, improved and contract-guarded. Full summary in `MAGI.md`. |
| test gaps, and the merge | `cca7d28`.. | `nws.py` had no tests; the FROM/TOWARD flip and the two parsing traps are pinned now, and a negative peak-window index near midnight UTC was found on the way. `test_contract.py` now checks `risk_replay.json` too, not just the hand-drawn fake. Then the branch was merged to `main`, which until this point held nothing but a one-line README, and a repo-root `AGENTS.md` was added so the other two tracks' agents stay out of `backend/fire/`. |

### What the MAGI track settled

- Three dispositions -- calibrated, protective, sceptic -- over one shared scene.
  Consensus is an order statistic, not a vote loop, so ADVISORY (1 of 3),
  MAJORITY (2 of 3, shipped) and CONFIRMED (unanimous) nest for free.
- **The ensemble does not beat the best single model** on either fire, in any of
  four scoring windows. It is kept for the ADVISORY-to-CONFIRMED gap, which is
  the only error bar this engine can honestly draw -- not for accuracy.
- ADVISORY appearing to win three of four windows is the same detection-mask
  size bias recorded above: at +1.7 h the ranking is exactly the ranking of
  predicted area, biggest first.
- **Rejected knobs, do not re-add.** A wind veer for BALTHASAR-2 (moved its rank
  share by 2 points and the advisory footprint by -2 km2) and dropping fuel
  entirely for CASPER-3 (drew the advisory fringe across a reservoir).
