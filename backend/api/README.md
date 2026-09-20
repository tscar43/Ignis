# Ignis HTTP API

This API consumes the fire engine without modifying its modules or payloads.
Read [the published contract](../../demo_data/README.md) for field meanings.

## Start (PowerShell, repository root)

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m uvicorn backend.main:app --reload
```

If the documented interpreter does not exist, create it with Windows Python 3.12:
`py -3.12 -m venv .venv`. Do not use MSYS Python to create the Windows environment.
Open http://localhost:8000/docs.

## Fire endpoints

- `GET /fire`: published hand-drawn risk_demo.json, unchanged.
- `GET /fire?mode=live`: spread.risk_payload(), behind a 300-second TTL cache.
- `GET /fire?mode=replay&t=H3`: the published 2018 Camp Fire frame.
- `GET /scenario/T0`, `H1`, `H3`, or `H6`: same replay frames, unchanged.
  These contain fire data, not precomputed route plans.

The default is explicitly demo mode, so opening the API needs no network or key.
Live mode requires the engine's FIRMS_MAP_KEY setup and upstream connectivity.
The service uses the engine's fixed geographic area; it does not accept an
arbitrary area of interest. All file/engine results use contract.validate().
No response model reserializes the fire payload; replay and optional MAGI fields
survive unchanged.

Cache behavior:
- A successful fetch is fresh for five minutes, measured with a monotonic clock.
- One request refreshes an expired entry; concurrent requests receive the previous
  payload. Concurrent cold requests wait for the single initial fetch.
- On any refresh/validation failure, retain the last good payload. Retry at most
  once per 30 seconds after a failure.
- With no prior good result, return 503 and Retry-After: 30.
- X-Fire-Source, X-Fire-Stale, X-Fire-Cache-Age and X-Fire-Observation-Age
  describe the result in headers, exposed through CORS. They are not added to
  the shared JSON contract.
- X-Fire-Cache-Age measures time in this cache: when we last fetched. It says
  nothing about how old the data is, and a loader returning a valid but frozen
  payload reports zero forever. X-Fire-Observation-Age is the age of
  data_as_of.firms and is the one that answers "is the fire picture current".
  It is present when the payload carries a readable observation time; live
  planning gates on it separately from cache staleness. The UI should still
  display data_as_of.firms and data_as_of.weather.
- The cache is in memory per process; use one worker to avoid per-worker fetches.
  Restart loses the last good value. A cold fetch blocks until the engine returns;
  its upstream request timeouts apply. There is no background polling.
- Demo/replay fixtures are loaded once per process. Restart to pick up replacements.

## Routing

POST /plan accepts origin, household, mode (demo/replay/live), and t.
It uses the same fire service as /fire and reports cache metadata in headers.

The default road graph is the real OpenStreetMap drive network under
`backend/routing/osm/paradise.graphml`: 1,279 nodes and 2,863 directed edges
around Paradise, California. It is loaded locally; requests never download
roads. OSM road geometry, one-way connections and estimated travel times are
preserved. This covers the existing demo area, not the entire US map.
See [cache provenance and rebuild instructions](../routing/osm/README.md).

The default origin 39.76, -121.62 returns a plan using these roads and the
published demo fire polygons. Destinations under `backend/routing/demo` remain
**fictional shelters**, with unverified capacity and availability. They are not
real evacuation destinations. Replay T0 returns 422 because all four fictional
shelters are inside the current fire. Do not interpret that as a real-world
absence of evacuation options.

Agent smoke test (no keys or network required):

```powershell
Invoke-RestMethod http://localhost:8000/plan -Method Post -ContentType 'application/json' -Body '{"origin":{"lat":39.76,"lon":-121.62},"mode":"demo"}'
```

Treat a 422 response as an unavailable plan and show its `detail`; never invent
a route. `/chat` remains a 501 stub for the frontend agent to implement.

`IGNIS_GRAPH_PATH` selects a different prepared GraphML file and
`IGNIS_SHELTERS_PATH` selects a matching shelter JSON file with the existing
Shelter fields. Restart after changing configuration or replacing a road cache.
To explicitly use the old synthetic network for a deterministic presentation:

```powershell
$env:IGNIS_GRAPH_PATH = 'backend/routing/demo/graph.graphml'
```

Unit tests select this synthetic graph and inject separate synthetic hazards to
verify that a 4-minute route through 1-hour risk is omitted and the eligible
9-minute bypass is returned. Generate
only those backend-owned fixtures with
`./.venv/Scripts/python.exe scripts/build_demo.py`. Integration tests use the real
OSM cache and published fire payloads, checking road geometry, current-fire
avoidance, household filtering and blocked replay behavior.

The engine output feeds route scoring as plain dictionaries. `/plan` first
blocks current fire and the modeled 1-hour risk region, including origin and
destination access connectors. It then chooses the quickest eligible shelter
and road route. Distances within cumulative bands are counted once, at the
most severe band covering each segment:

`weighted_km = 10*h1_km + 4*h3_km + h6_km`

`exposure = clamp(weighted_km/(10*route_distance_km), 0, 1)`

The exposure metric describes the route; it does not override travel-time
ranking after exclusions. Any 3-hour/6-hour exposure produces a warning.
These checks are a routing policy, not a certification of safety.

**Frontend change:** `routes` contains one `recommended` route and at most one
`alternative`. Do not assume exactly two entries or a `fastest` entry. A second
route must meet the same exclusions, have different geometry, share at most
80% of the shorter route's edge length, and take no more than 50% longer.
Search inspects at most 20 shortest simple paths; no alternative means none was
found under these limits. Missing/stale evacuation input suppresses alternatives.

Fresh supplied evacuation order and warning zones cannot be entered. An origin
already inside a zone may follow a contiguous exit, without re-entry; destinations
inside restricted zones are excluded. This is a conservative application policy,
not an assertion that every warning zone is an official road closure.

Coordinates are [lon, lat], times are minutes and distances are kilometres.
Snap distances over 1 km are rejected (50 m for reviewed FEMA entrances).
Connectors are checked for excluded hazards/zones but are not modeled driving
segments; their time, distance, and longer-horizon exposure are not included.
Traffic, live road closures, turn restrictions and live available beds are not modeled.

GET /shelters filters static fictional shelter data. POST /geocode recognizes
123 Oak St / Street only. POST /chat remains 501 pending the frontend-owned agent.

## Verification and next work

```powershell
./.venv/Scripts/python.exe -m pytest -q
```

Tests cover payload equality, all replay frames, TTL, invalid/failed refreshes,
retry throttling, concurrent fetches, additive fields, CORS, route selection,
current-fire blocking and shelter constraints. End-to-end routing tests also use
the published demo/replay payloads without substituting synthetic hazards.
All tests run offline.

Remaining handoff: the frontend owns the AI agent and map/banner rendering.
Live use still needs fresh evacuation input and verified eligible shelter access.
The route-array changes above must be reflected in the frontend.

## Local FEMA shelter preview

See [shelter integration](../shelters/README.md) for the source, local refresh,
nullable policy fields, and reviewed-entrance requirements. `GET /shelters/catalog`
shows the real Butte County catalogue and access gaps; `GET /shelters?source=fema`
filters eligible records. `POST /plan` accepts `shelter_source=fema`. Defaults
retain the fictional demo. Closed/stale/unknown-required records never silently
fall back to demo destinations.

## Palisades judging demo and frontend handoff

No keys or network are needed at runtime. Start the API normally, then:

- `GET /demo/palisades` supplies the historical evacuation GeoJSON, matching
  fire replay, default origin/destination, and banner text.
- `POST /demo/palisades/plan` accepts `apply_evacuation_orders` (default `true`)
  and optional `origin` and `destination` coordinates. Send `{}` to use the
  verified comparison points.

```powershell
Invoke-RestMethod http://localhost:8000/demo/palisades
Invoke-RestMethod http://localhost:8000/demo/palisades/plan -Method Post -ContentType 'application/json' -Body '{"apply_evacuation_orders":true}'
Invoke-RestMethod http://localhost:8000/demo/palisades/plan -Method Post -ContentType 'application/json' -Body '{"apply_evacuation_orders":false}'
```

Frontend: draw `evacuations.features` from the GET response as the map overlay
(`properties.level` is `order` or `warning`). Use red for orders and amber for
warnings. Render the returned `banner.title`, `banner.message`, `banner.as_of`
and linked `banner.source_url` prominently. The frontend owns styling and the
AI agent. The toggle changes the POST request, not the stored polygon or fire
payload. Keep the polygon visible in both views so judges can see the crossing.
Replace map routes with each new response; cancel/ignore older responses when
users toggle quickly. On 422, clear the prior route and display `detail`.

With restrictions ON, `routes[0].type` is `recommended`. With restrictions OFF,
it is `comparison`, `comparison_only` is true, no alternatives are offered, and
the banner states that evacuation restrictions are ignored. Current-fire and
1-hour exclusions remain enabled in both states. The toggle exists only on this
historical demo endpoint and cannot disable restrictions in live `/plan`.

The fixed January 8, 2025 03:00 Pacific snapshot contains one archived order
polygon and four warning polygons. It is not a current alert. The source's daily
backup timestamp is not the original issuance time. See
[asset provenance](../routing/demo/PALISADES.md). The selected destination is
an arbitrary demonstration road point, **not a verified shelter**. Roads are a
current OSM cache, not reconstructed 2025 traffic or closure conditions.

## Current evacuation input (optional, separate from the historical demo)

`GET /evacuations?lat=...&lon=...` reports status, coverage, source polygons and
orders covering the location. No configured data means `status: unknown`, not
an all-clear. `mode` defaults to `live`; source mode must match the request.

Set `IGNIS_EVACUATIONS_PATH` to an operator-maintained local JSON snapshot.
This is a read-only integration, not an automatic official-feed subscription.
The validated shape is `OrderSnapshot` in `backend/api/evacuations.py`: a
FeatureCollection with `mode`, timezone-aware `fetched_at`, `source_url`,
`authority`, EPSG:4326 polygon `coverage`, and `features`. Each feature has
polygon geometry and properties `id`, `zone`, `level` (`order`, `warning`,
`lifted`), `authority`, `source_url`, `updated_at`, `valid_until`, `instructions`.
Only declare coverage that the input actually covers; an empty feature list is
not proof of conditions outside that area. Replace the complete snapshot
atomically when orders are changed/lifted.

Snapshots older than 30 minutes, future-dated snapshots, or any expired record
are stale. Supplied coverage must contain the complete route and access
connectors. Invalid configured files return 503. Historical Palisades assets
are served separately and never treated as fresh live orders.

Live planning returns 503 on any of four separate conditions, because they
fail for different reasons and only one of them is fixed by refetching:

1. No fresh matching evacuation input for the origin.
2. The fire cache is stale -- the refresh loop is behind.
3. The newest fire observation is older than MAX_OBSERVATION_AGE_S, or its
   timestamp cannot be read. A recent fetch of old detections is not fresh
   data, and the cache alone cannot tell the difference.
4. The configured road graph falls outside the bbox the fire engine models.
   Such a graph routes normally and reports no hazards at all, because the
   fire polygons are somewhere else -- an empty intersection that reads as
   safety. Evacuation coverage is checked separately and does not cover this.

## Deployment readiness

`GET /health` checks process liveness. `GET /ready` loads and validates the local
Paradise/Palisades demo inputs and road caches; it returns 503 if a required
asset is missing or malformed. This does not claim that live feeds, current
shelters or evacuation orders are available. Loaded immutable demo/road assets
are cached until restart.

Set the comma-separated `IGNIS_CORS_ORIGINS` in the server environment to allow
the deployed frontend origin. Defaults remain localhost ports 5173 and 3000.
For PowerShell, before starting Uvicorn:

```powershell
$env:IGNIS_CORS_ORIGINS = 'https://your-frontend.example,http://localhost:5173'
```

Writing a setting into `.env` alone does not load it into this API's environment.
Use your hosting platform's environment settings or export it before startup.
Malformed/missing road or Palisades assets return 503; invalid request coordinates
and requests with no eligible route return 422. `/chat` is still the
frontend-owned integration stub, and general-purpose geocoding is not implemented.
