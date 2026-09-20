# Fire spread & geospatial engine

Turns satellite fire detections, wind, fuel and terrain into 1h/3h/6h risk
polygons the routing engine avoids. Developed on `fire-engine`, merged to
`main`.

Three docs, no overlap: **this** is orientation, `FINDINGS.md` is what the
model experiments settled, `AGENTS.md` is the rules. `MAGI.md` covers the
ensemble. Read `AGENTS.md` and `FINDINGS.md` before changing the model.

**Status:** all nine milestones from the role brief are done and merged.
Tests green. Runs live or in replay against real data, not fixtures.
Repo-wide rules, and who owns what, are in the root `AGENTS.md`.

## Run it

```bash
P=./.venv/Scripts/python.exe                # every doc here uses this interpreter
$P -m backend.fire.spread                   # replay the Camp Fire, print the summary
$P -m backend.fire.spread --live            # current NRT hotspots + NWS wind
$P -m backend.fire.spread --replay          # write demo_data/risk_replay.json
$P -m backend.fire.national                 # model every active fire in CONUS
$P -m backend.fire.national --list          # just find them: no rasters, no wind
$P -m backend.fire.wfigs                    # NIFC's current incident list, by size
$P -m backend.fire.magi                     # MAGI ensemble: three models deliberate
$P -m backend.fire.validate                 # IoU ablation across validation fires
$P -m backend.fire.palisades                # Palisades 2025, vs the standard model
$P -m backend.fire.palisades --json         # the same windows as GeoJSON, for /palisades
$P -m backend.fire.elliptical               # the ellipse's LB ratio by wind speed
$P -m backend.fire.rothermel                # spread rate per fuel model by wind
$P -m backend.fire.contract                 # check shipped payloads against the contract
$P -m backend.fire.landfire --overlay       # write demo_data/fuel_overlay.png
$P -m backend.fire.goes W S E N             # newest GOES ABI frame for a bbox
$P -m pytest backend/fire/tests -q          # 135 tests, all offline, ~1 s
```

Entry points run with `-m`: `backend/` is a package and the modules import
relatively. Call the venv interpreter by path rather than a bare `python` --
the venv is not activated in a fresh shell, and `python` there is the system
3.14 with none of the geospatial wheels. Needs `.venv` (Python 3.12) and
`FIRMS_MAP_KEY` in `.env`.

```python
from backend.fire.spread import risk_payload
risk_payload()          # live: NRT hotspots + current NWS wind
risk_payload(when=dt)   # replay: SP archive + reanalysis wind for that hour

from backend.fire.national import discover, national_payload
discover()              # every active CONUS incident, ranked by radiative power
national_payload()      # the top 12 of them, each a full contract payload
```

`national.py` picks the boxes instead of being handed one: it clusters a
single CONUS FIRMS query into incidents and runs `risk_payload()` per
incident, in a process pool, with the cluster's own detections passed in so
the country costs one FIRMS request rather than one per fire. Served as
`/fires`. Known edges, all commented at the code: only the top `limit` fires
are modelled, a cluster wider than `MAX_SPAN_DEG` is clipped to its middle,
and CONUS excludes AK and HI because `landfire.SERVICES` has no `_AK`/`_HI`
entry.

`wfigs.py` joins that to NIFC's own record, and it is what makes the national
view legible rather than a wall of coordinates:

- **Names.** A cluster becomes "the Dome fire, 2384 acres, 15% contained",
  with an IRWIN id, which is the key every other agency feed joins on.
- **Ranking.** FIRMS cannot tell a wildfire from a burning field -- both are
  hot 375 m pixels, and by radiative power alone the top twelve fires in the
  country were eleven Mississippi Delta crop burns and one wildfire. A cluster
  with a WFIGS incident record is one an agency is responding to, so those
  rank first, and fully contained ones sort below the rest.
- **Seeding.** Where an agency has mapped a perimeter, `spread.gather()`
  unions it into the ignition mask. Detections mark where a fire is *hottest*;
  the perimeter is where its edge actually is. The union is the honest seed:
  the perimeter says how big, the fresh detections say how far it has run
  since the flight that mapped it.
- **What counts as current.** `currently_active()` drops three things: fires
  the agency has fully contained, incidents nobody has touched in a week, and
  industrial heat that will be exactly as hot tomorrow. On one sweep that was
  1 contained fire and 60 static sources out of 605 clusters.

This is the opposite of competing with NIFC. Their data is the ground truth
the projection sits on; the projection is the part they do not publish.

## Modules

| module | does |
|---|---|
| `firms.py` | FIRMS hotspots, live (NRT) and archive (SP), disk-cached |
| `goes.py` | GOES ABI fire pixels, newest frame, ~5 min old. Live freshness seed |
| `landfire.py` | fuel/slope/aspect rasters, the F_fuel lookup, the map overlay |
| `terrain.py` | F_slope, directional, from slope and aspect |
| `spread.py` | arrival-time Dijkstra, polygonize, `risk_payload()`, `replay()` |
| `national.py` | one FIRMS query over CONUS -> clustered incidents -> a payload per fire |
| `wfigs.py` | NIFC WFIGS: official incident names, acreage, containment, perimeters |
| `contract.py` | machine-checkable contract: `validate()` / `check()` |
| `validate.py` | IoU ablation against real fires — results in `FINDINGS.md` |
| `elliptical.py` | the Alexander/Finney ellipse FARSITE-class tools use, as a baseline |
| `rothermel.py` | Rothermel/Albini surface spread and the 40 fuel models. No fitted R0 |
| `palisades.py` | Palisades 2025 three-way comparison, its figure, and `--json` for the replay tab |
| `magi.py` | Three-model ensemble, consensus by order statistic. `magi.risk_payload()` is a drop-in for `spread.risk_payload()`. See `MAGI.md`. |
| `make_demo_data.py` | the hand-drawn day-one fake, superseded, kept as a fixture |
| `../weather/nws.py` | wind: HRRR live (NWS gridpoint fallback), Open-Meteo archive for replay |

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

**GOES.** The CONUS sector (`FDCC`) scans every 5 minutes; the file reaches
S3 about 3 minutes after scan start, anonymously, no key. The filename's `_s`
field is year + **day-of-year** + HHMMSS -- parsing it as `%Y%m%d` lands in the
wrong month and still looks like a timestamp. Mask values below 10 are not
fire; the 3x codes are the 1x categories confirmed across frames. An ABI cell
is kilometres wide, so a GOES detection seeded at VIIRS's 375 m marks one
120 m grid cell and the morphological closing then deletes it -- the detection
is fetched, geolocated correctly, and silently does nothing. That is what
`Hotspot.pixel_m` exists for, and `test_goes.py` pins it.

**Live after midnight.** A FIRMS query with no date means *today in UTC*, and
NRT publishes a pass some hours after it happens -- so from 00:00Z until the
first pass of the day lands, "latest" is an empty CSV. At 01:27Z it returned
zero detections for the whole of CONUS while the previous UTC day had 911.
That reads as "no fires", not as "no data yet". `firms.fetch_live()` asks for
two days and lets the caller keep the newest pass, which is what the live path
already did.

**Parallel cache writes.** Running incidents concurrently means several
workers want the same GOES frame. Windows refuses to rename over a file
another one has open, so a plain write-then-replace failed four incidents out
of twelve with `Access is denied`. `firms.cache_write()` writes a temp file,
and on a lost race keeps whoever got there first -- every cache key here is
derived from the request, so the two files are the same bytes.

**The solver holds the GIL.** `arrival_times` is a Python `heapq` loop, not a
numpy kernel, so it does not release the GIL for its whole run. Six of them in
a thread pool inside uvicorn starved the event loop so completely that
`/health` timed out at 20 s while a national run was in flight -- the API was
dark for minutes, which in a demo looks like a crash. `national.py` uses a
`ProcessPoolExecutor`: the per-fire work is a dict in and a dict out, so it
ships to a worker unchanged, and the server stays at 0.2 s throughout. A
national run of 12 fires takes ~10 s warm.

**"Current" means the current season.** The WFIGS *Current* layers carry the
year, not the night: 215 of 342 CONUS records were reported more than two
weeks ago, 90 more than two months. The obvious close-out fields are no help,
because `FireOutDateTime`, `ControlDateTime` and `ContainmentDateTime` are
null on every record in the layer. What works is containment plus the record's
own last-modified stamp -- an incident somebody is still working gets touched
daily. Age alone is the wrong test: Border 2 was reported 65 days ago, is 74%
contained, was updated today, and is a real fire burning right now.

**Detection age is not a filter.** The tempting next step is to drop clusters
whose newest pass is over 24 h old. Measured on a live sweep, that would have
dropped 4 of 13 active incidents -- they had no clear overpass, which is the
exact staleness this engine exists to be honest about, not a reason to hide a
fire. The age is surfaced in the payload and coloured in the UI instead.

**Industrial heat.** VIIRS measures radiant heat, not what is burning, so a
landfill flare, a refinery and a steel mill are all genuine thermal anomalies
and all look like small wildfires. The `type` field FIRMS uses to mark "other
static land source" **does not exist in the NRT feed** -- only in the SP
archive -- so `vegetation_only=True` is a silent no-op on every live call.
What separates them is persistence: a wildfire does not burn the same 1 km
cell for five straight days without an incident record, and a flare does.
`national.PERSISTENT_DAYS` is that test, and it cost one extra day of FIRMS
history, not a new data source.

**WFIGS matching.** A wrong name is worse than no name -- an unrelated
refinery flare labelled with an official incident number looks authoritative.
Two real failures are pinned in `test_wfigs.py`. A fixed 15 km match radius
put three Los Angeles County brush calls on industrial heat over the harbour,
because in a dense county something is always within 15 km; the radius now
scales with reported acreage, and a 30-acre fire cannot claim a hotspot 12 km
out. A perimeter that *contains* a cluster wins over one that merely
intersects it, smallest first, so a new fire inside an old 300,000-acre burn
scar is still the new fire. And fires whose detections split into two clusters
are merged on their shared IRWIN id -- otherwise "Border 2" models and draws
twice, with two different wind readings.

**Wind.** Both sources report the direction wind comes FROM. Everything
leaving `nws.py` is already flipped to TOWARD, so do not flip it twice --
`tests/test_nws.py` pins the flip at the source and `test_spread.py` pins it
downstream. ERA5
reanalysis is ~25 km and smooths terrain-driven wind away, which is what
`archived(peak_window_h=...)` exists for. An NWS gridpoint series starts at the
last issuance boundary, not at the current hour, so `values[0]` is not "now" --
it read 7 h stale on a live run and shipped as `data_as_of.weather`. Speed and
direction break at different times, so each series is selected separately.
`live()` now prefers HRRR at 3 km and keeps the gridpoint as a fallback.

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
