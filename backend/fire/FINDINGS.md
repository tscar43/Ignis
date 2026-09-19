# Fire engine: what the experiments settled

What a new session needs before touching the model: which questions are
already answered, so nobody re-runs a dead end. `AGENTS.md` is the rules,
`README.md` is the current state, this is the evidence.

Detail lives in commit messages and in `validate.py`'s docstring. This file
points at it rather than restating it, so the two can't drift.

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
