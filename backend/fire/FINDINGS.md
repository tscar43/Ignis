# Fire engine: what the experiments settled

What a new session needs before touching the model: which questions are
already answered, so nobody re-runs a dead end. `AGENTS.md` is the rules,
this is the evidence. All nine milestones from the role brief are done and
pushed on `fire-engine`; the engine runs live or in replay against real FIRMS,
LANDFIRE and ERA5 data.

Detail lives in commit messages and in `validate.py`'s docstring. This file
points at it rather than restating it, so the two can't drift. A session log at
the end summarises every work block on the branch, including the MAGI ensemble
track that ran in parallel.

## The ablation

`python -m backend.fire.validate` scores wind-only against wind+fuel and
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
| MAGI ensemble | **uncommitted** | `magi.py` and `tests/test_magi.py`, improved and contract-guarded. Full summary in `MAGI.md`. |

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
