# MAGI ensemble — state of play

Three spread models deliberate over the same observations; the shipped payload is
their 2-of-3 median. Named for Evangelion's supercomputers. Lives in
[magi.py](magi.py), tested in [tests/test_magi.py](tests/test_magi.py).

Read this before touching `magi.py`. The reasoning behind every number here is in
that module's docstring; this file is the map, not the territory. For the engine
as a whole see `README.md`, and for the ablation's settled dead ends `FINDINGS.md`.

## What it is

| Magus | Doctrine | Knobs |
|---|---|---|
| MELCHIOR-1 | calibrated physics as fitted | defaults |
| BALTHASAR-2 | protective: the gusts ERA5 smoothed away | `wind_gain=1.8`, `r0_gain=1.25` |
| CASPER-3 | sceptic: barriers yes, fuel weighting and slope no | `r0_gain=0.8`, `use_fuel=False`, `use_slope=False` |

Consensus is an **order statistic, not a vote loop**. Sort the three arrival-time
grids per cell: soonest = `advisory` (1 of 3), middle = `majority` (2 of 3,
**shipped**), latest = `confirmed` (unanimous). Sorting is monotone, so the levels
nest by construction — the same trick `bands_to_geojson` uses for h1 ⊆ h3 ⊆ h6.

`magi.risk_payload()` has the same name and shape as `spread.risk_payload()`, so
an endpoint swaps one import. Extras are additive: a top-level `magi` block
(doctrines, per-model and per-level areas, `confidence` polygons for all three
levels) and `summary.magi_verdict`, a one-liner for the chat model.

## Run it

```bash
./.venv/Scripts/python.exe -m backend.fire.magi            # replay deliberation table
./.venv/Scripts/python.exe -m backend.fire.magi --live     # NRT hotspots + NWS wind
./.venv/Scripts/python.exe -m backend.fire.magi --score    # IoU on both validation fires
./.venv/Scripts/python.exe -m backend.fire.magi --write    # demo_data/risk_magi.json
```

`--score` hits Open-Meteo's archive fresh every run (the cache is per-process), so
it can die on a transient `WinError 10054`. Retry; don't demo it cold.

## The honest result

The majority does **not** beat the best single model, on either validation fire.
Growth-only IoU, same fires and scoring days as [validate.py](validate.py)'s
ablation:

| | Camp +1.7 h | Camp +11.4 h | Dixie +1.7 h | Dixie +10.5 h |
|---|---|---|---|---|
| MELCHIOR-1 | 0.136 | 0.272 | 0.064 | 0.272 |
| BALTHASAR-2 | 0.243 | 0.293 | 0.126 | 0.355 |
| CASPER-3 | 0.231 | **0.361** | 0.101 | 0.289 |
| ADVISORY | **0.268** | 0.299 | **0.146** | **0.359** |
| MAJORITY | 0.208 | 0.339 | 0.091 | 0.303 |
| CONFIRMED | 0.130 | 0.284 | 0.053 | 0.250 |

MAJORITY loses all four windows and ADVISORY wins three — but **that is not
skill**: at +1.7 h on both fires the ranking is exactly the ranking of predicted
area, biggest first. Ground truth is FIRMS detections and a cell that burned and
cooled stops being reported, so at short range this metric rewards size. The one
window where shape beats size is Camp +11.4 h, where CASPER-3 predicts less than
MAJORITY, BALTHASAR-2 and ADVISORY and still wins — the ablation's wind-alone
result showing up in the ensemble.

So the ensemble is kept for the **uncertainty band, not for accuracy**. Do not
re-tune the doctrines to win that table; that is fitting three models to two
fires, which is the mistake `validate.py` exists to catch.

## Non-obvious facts that cost time to establish

- **BALTHASAR-2 can never set CONFIRMED.** More wind and a faster R0 only ever
  arrive sooner, so it is never the slowest of the three: CONFIRMED is exactly
  Melchior ∩ Casper. Its vote lands on MAJORITY, where it is the median on 64% of
  the 13.6k cells all three reach. A 20° wind veer was tried so it could disagree
  about direction too — moved its rank share by 2 points and the advisory
  footprint by −2 km², so the knob was deleted.
- **`use_fuel=False` is not validate.py's wind-only config.** It keeps the
  non-burnable zeros and flattens only the 0.2–1.0 weighting. Ignoring fuel
  entirely drew an advisory fringe across a reservoir. Keeping the barriers cost
  0.018 growth-IoU at +1.7 h and 0.003 at +11.4 h, and removed 26 km² of 11.4 h
  footprint sitting on water or bare rock.
- **CASPER-3's known blind spot is short range on steep ground.** Dixie +1.7 h is
  validate.py's one *positive* result for the derived terms, and slope carries it.
  Casper drops slope anyway — dissent is its job, and the ADVISORY↔CONFIRMED gap
  is where that disagreement is supposed to show.
- **Two area measures, never mix them.** `magi.area_km2` is raster cell counts
  (comparable across models and levels: CONFIRMED ≤ every model ≤ ADVISORY holds
  exactly). `magi.confidence[level].area_km2` is polygon area, ~5% higher because
  the closing that makes the rings drawable also fills their pinholes.
- **The drawn rings nest only to a tolerance.** The grids nest exactly, but each
  level is closed and simplified separately, so the rings overlap by ~1.5e-5 of
  their area (~100 m²). Pinned as a test tolerance rather than re-unioning the
  polygons.
- **The payload is contract-checked on the way out** — the whole payload and each
  confidence level as a standalone payload, since `assemble()` carries no guard
  and this function is advertised as a drop-in for `spread.risk_payload`.

## Open, in rough priority order

1. Per-magus R0 calibration via `validate.calibrate`, so the IoU table compares
   shape rather than partly size. Against: it is fitting to two fires.
2. A `confidence=False` fast path. Three levels × four bands = 12 polygonizations
   is most of `risk_payload`'s local runtime.
3. CASPER-3 veering the wind the other way, to put direction uncertainty into
   ADVISORY. Real uncertainty; the sign is not defensible from two fires.
4. A dissent layer (which magus disagreed where) if the map wants to label the
   fringe.
5. `score()` reaches into `validate._setup` (private). Promote it if that
   module's owner agrees; a guard test fails loudly if it is renamed.

## Session notes

- `magi.py` and `tests/test_magi.py` were first committed by another session
  inside `40bcb40` (milestone 9), which used `git add -A`. The improvements
  since then are `6f1a812`, and the branch is pushed.
- That other session owns `validate.py` and `contract.py` and has been editing
  them concurrently. A full-suite run during one of its writes produced a bogus
  `test_contract.py` failure; re-run before believing a failure there.
