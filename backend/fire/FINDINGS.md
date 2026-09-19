# Fire engine: state and findings

Orientation for a new session. Detail lives in commit messages and module
docstrings; this file only says where it is and what is already settled.

## Where it stands (2026-09-19)

All nine milestones from the role brief are committed on `fire-engine`
(`fb4e0b0`..`067c9b0`) and pushed. `spread.risk_payload()` is the contract
payload, built from live FIRMS / LANDFIRE / NWS. Replay frames, the fuel
overlay and IoU validation all run against real data, not fixtures.

## The validation result, and what is already ruled out

`python -m backend.fire.validate` scores the ablation on two fires. Read
`validate.py`'s docstring before touching the model -- it records the dead
ends so nobody re-runs one. Growth-only IoU:

```
                        Camp 2018-11-09       Dixie 2021-07-16
                      +1.7 h     +11.4 h     +1.7 h     +10.5 h
  wind only            0.279       0.385      0.232       0.376
  wind+fuel            0.284       0.314      0.222       0.353
  wind+fuel+slope      0.274       0.314      0.259       0.334
```

- **Fuel and slope do not improve IoU on either fire.** Wind alone wins at the
  ~10 h horizon on both. Say this openly; do not claim otherwise in the pitch.
- **The regime explanation is dead.** Camp suggested the terms lose because a
  35 km/h fire is wind-driven rather than fuel-limited. Dixie's first week
  tested it -- same canyon 10 km upriver, same terrain and fuel vintage and
  ERA5 cell, 13 km/h instead of 35 -- and the ordering did not reverse.
- **Slope earns its place at short range in steep ground.** Dixie +1.7 h is the
  one case the full model wins (0.259 vs 0.232), and slope carries it: fuel
  alone scores worse than no fuel.
- **Also ruled out:** unfair calibration (each variant gets its own R0), urban
  as a hard barrier (moved IoU by 0.001), and fuel vintage on Dixie (mean
  F_fuel 0.527 LF2016 vs 0.531 LF2022 inside the footprint).
- **Leading untested suspect:** calibration. `F_fuel <= 1` averaging ~0.5 forces
  R0 up 2-3x, so fuel runs drive grass corridors at near-full rate while timber
  lags. Testing it needs a shape metric, not IoU.

Keep the fuel and slope terms regardless: they are what make barriers and
terrain visible, which the contract's consumers need.

## Open, deliberately not started

- `contracts/` is empty, though `AGENTS.md` and `demo_data/README.md` both
  point teammates at it. A schema there would close the dangling reference.
- No HTTP endpoint exists anywhere in the repo. The brief asks for one, but
  the backend teammate may want to own the app entry point -- ask before
  building it. `risk_payload()` also refetches everything per call, so an
  endpoint needs a TTL cache to be usable live.
- `magi.py` (three-model ensemble over the same contract) is in flight in a
  separate session as of 2026-09-19. Leave it and `tests/test_magi.py` alone.

## Lane

Only `backend/fire/`, `backend/weather/`, `demo_data/risk_*`, and
`fuel_overlay.png`. `contracts/` is shared -- agree with the team first. See
`AGENTS.md` for the rest of the rules.
