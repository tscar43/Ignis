# Fire spread & geospatial engine

Turns satellite fire detections, wind, fuel and terrain into 1h/3h/6h risk
polygons the routing engine avoids. Lives on the `fire-engine` branch.

Three docs, no overlap: **this** is orientation, `FINDINGS.md` is what the
model experiments settled, `AGENTS.md` is the rules. `MAGI.md` covers the
ensemble. Read `AGENTS.md` and `FINDINGS.md` before changing the model.

**Status:** all nine milestones from the role brief are done and pushed.
Tests green. Runs live or in replay against real data, not fixtures.

## Run it

```bash
python -m backend.fire.spread              # replay the Camp Fire, print the summary
python -m backend.fire.spread --live       # current NRT hotspots + NWS wind
python -m backend.fire.spread --replay     # write demo_data/risk_replay.json
python -m backend.fire.magi                # MAGI ensemble: three models deliberate
python -m backend.fire.validate            # IoU ablation across validation fires
python -m backend.fire.contract            # check shipped payloads against the contract
python -m backend.fire.landfire --overlay  # write demo_data/fuel_overlay.png
python -m pytest backend/fire/tests -q
```

Entry points run with `-m`: `backend/` is a package and the modules import
relatively. Needs `.venv` (Python 3.12) and `FIRMS_MAP_KEY` in `.env`.

```python
from backend.fire.spread import risk_payload
risk_payload()          # live: NRT hotspots + current NWS wind
risk_payload(when=dt)   # replay: SP archive + reanalysis wind for that hour
```

## Modules

| module | does |
|---|---|
| `firms.py` | FIRMS hotspots, live (NRT) and archive (SP), disk-cached |
| `landfire.py` | fuel/slope/aspect rasters, the F_fuel lookup, the map overlay |
| `terrain.py` | F_slope, directional, from slope and aspect |
| `spread.py` | arrival-time Dijkstra, polygonize, `risk_payload()`, `replay()` |
| `contract.py` | machine-checkable contract: `validate()` / `check()` |
| `validate.py` | IoU ablation against real fires — results in `FINDINGS.md` |
| `magi.py` | Three-model ensemble, consensus by order statistic. `magi.risk_payload()` is a drop-in for `spread.risk_payload()`. See `MAGI.md`. |
| `make_demo_data.py` | the hand-drawn day-one fake, superseded, kept as a fixture |
| `../weather/nws.py` | wind: NWS live, Open-Meteo archive for replay |

## The contract

`contract.py` is the checkable version; `demo_data/README.md` is the prose for
teammates. Two rules matter most, and no JSON schema expresses either:

- Coordinates are **`[lon, lat]`**, EPSG:4326, in that order.
- Bands are **cumulative**: `h6 ⊇ h3 ⊇ h1 ⊇ current`. Regions, not rings.

`risk_payload()` returns through `contract.check()`, so an invalid payload
raises instead of reaching the UI. That guard sits on `risk_payload()` and
deliberately **not** in `assemble()`, which `magi.py` also calls -- so
`magi.risk_payload()` carries its own `check()`, on the payload and on each
confidence level.

`contracts/` at the repo root is still empty and is shared. `contract.py` is
the proposed content; moving it there needs team sign-off.

## Traps already paid for

**FIRMS.** Day range maxes at 5, not 10. `acq_time` is HHMM with leading zeros
dropped, so 00:50 UTC arrives as `"50"` and naive parsing shifts a pass four
hours. A quoted value in `.env` reaches the API with the quotes and comes back
as `Invalid MAP_KEY.`, which looks exactly like a dead key. A detection is a
~375 m pixel — not a point, not a perimeter.

**LANDFIRE.** The image service does clip + reproject + resample in one GET:
no national download, no warp code. Nearest-neighbour always, because FBFM40
codes are categories and interpolating them invents fuel models that do not
exist. `SlpD` is degrees, `SlpP` is percent rise, and the layer name is the
only thing that says which. Aspect is the direction the slope *faces*, which
is downslope — uphill is `aspect + 180`, and backwards runs fire into the
valley while still looking plausible on a map. There is a test for that one.

**Wind.** Both sources report the direction wind comes FROM. Everything
leaving `nws.py` is already flipped to TOWARD, so do not flip it twice. ERA5
reanalysis is ~25 km and smooths terrain-driven wind away, which is what
`archived(peak_window_h=...)` exists for.

**Geometry.** Snap coordinates *before* the final union, never after —
snapping a union's intersection vertices moves them off the inner band's edge
and breaks nesting. `simplify()` can bite into the inner band, so re-union
after it. GEOS `covers()` reports False on correctly nested bands by a float
epsilon, so check leaked area rather than the predicate.

**Model.** The brief's linear wind term gives a head:flank ratio of 1.8 and
spreads a blob; cubing it gives 5:1, inside the real 4:1–10:1 range. Seed from
**one** satellite pass — older detections are already-burned area, and seeding
them projects the same fire twice. `R0` is fitted per incident.

## Working agreements

- **Never `git add -A` here.** Other sessions edit this tree concurrently and
  the git index is shared. Stage explicit paths and read
  `git diff --cached --name-only` before committing. This has already filed
  another session's work under the wrong commit message (`a7acf52`,
  `40bcb40`) and lost an uncommitted doc edit to a concurrent write.
- `git fetch origin` and check divergence before every push.
- Stay in `backend/fire/`, `backend/weather/`, `demo_data/risk_*`,
  `fuel_overlay.png`. `contracts/` is shared.
- Never commit `.env`, `.tif`, or anything over 10 MB. `cache/` is gitignored.
