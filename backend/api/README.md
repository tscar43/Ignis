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
- X-Fire-Source, X-Fire-Stale and X-Fire-Cache-Age describe the result in headers,
  exposed through CORS. They are not added to the shared JSON contract.
- Age measures time in this cache, not satellite observation age. The UI should
  always display data_as_of.firms and data_as_of.weather.
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
verify a 4-minute direct route versus a 9-minute lower-exposure bypass. Generate
only those backend-owned fixtures with
`./.venv/Scripts/python.exe scripts/build_demo.py`. Integration tests use the real
OSM cache and published fire payloads, checking road geometry, current-fire
avoidance, household filtering and blocked replay behavior.

The engine output feeds route scoring as plain dictionaries. Current-fire edges
are blocked for both route types. Each remaining edge uses its most severe
intersecting band; only the intersection length in that band is counted.

`weighted_km = 10*h1_km + 4*h3_km + h6_km`

`cost_minutes = travel_time_seconds/60 + 4*weighted_km`

`exposure = clamp(weighted_km/(10*route_distance_km), 0, 1)`

Lower bands on a long edge are omitted by this edge-level approximation.
Recommended minimizes time plus exposure cost; fastest minimizes time to the same
selected eligible shelter. Coordinates are [lon, lat]; output units are minutes
and kilometres. Snap distances over 1 km are rejected. Access segments, traffic,
live capacity, turn restrictions and official road closures are not modeled.
Origin/destination access segments can be hundreds of metres and are not
routed or assessed for fire exposure; the response discloses snap distances.

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

Next: supply an approved shelter catalogue and validate its access routes and
coverage. The frontend agent can already consume `/plan`; real-road routing
needs no fire-model or response-schema changes.

## Local FEMA shelter preview

See [shelter integration](../shelters/README.md) for the source, local refresh,
nullable policy fields, and reviewed-entrance requirements. `GET /shelters/catalog`
shows the real Butte County catalogue and access gaps; `GET /shelters?source=fema`
filters eligible records. `POST /plan` accepts `shelter_source=fema`. Defaults
retain the fictional demo. Closed/stale/unknown-required records never silently
fall back to demo destinations.
