# Ignis

Wildfire evacuation demo. Satellite fire detections, wind, fuel and terrain in,
1h/3h/6h risk polygons out, for routing and a map to consume.

Three people are building this in parallel. **Agents: read
[AGENTS.md](AGENTS.md) before editing** — it says who owns what and which
directories not to touch.

## What's here

| | |
|---|---|
| `backend/fire/` | the spread engine — start at [backend/fire/README.md](backend/fire/README.md) |
| `backend/weather/` | wind: HRRR live, Open-Meteo reanalysis for replay |
| `demo_data/` | shipped payloads and the consumer-facing contract prose |
| `contracts/` | shared, still empty — `backend/fire/contract.py` is the proposed content |

The fire engine is **done and merged**: nine milestones, runs live or in replay
against real FIRMS, GOES, LANDFIRE, HRRR and ERA5 data, not fixtures. 105
tests, all offline. Everything it ships is validated against the contract on
the way out, and scored against the 2025 Palisades Fire in
[demo_data/palisades_comparison.png](demo_data/palisades_comparison.png).

Not built yet: the HTTP endpoint, the backend API, the frontend. The endpoint
is deliberately unclaimed — see [AGENTS.md](AGENTS.md).

## If you are building against the fire engine

Read [demo_data/README.md](demo_data/README.md) first. It is the contract in
prose: key names, units, CRS, and the two rules that no JSON schema expresses
(`[lon, lat]` order, and bands that are cumulative rather than rings).

- `demo_data/risk_demo.json` — hand-drawn and deterministic, for building
  against. Values will change when you swap to the live engine; keys, units and
  CRS will not.
- `demo_data/risk_replay.json` — four real frames of the 2018 Camp Fire, for a
  scrubber.
- `demo_data/fuel_overlay.png` + `.json` — LANDFIRE fuel as a map overlay,
  EPSG:4326, bounds in Leaflet order.

Both payloads are checked against `backend/fire/contract.py` in the test suite,
so a drift shows up as a failing test rather than a broken map.

For a live payload, call the engine rather than reading a file:

```python
from backend.fire.spread import risk_payload
risk_payload()
```

## Setup

```bash
cp .env.example .env                        # then add a free FIRMS map key
./.venv/Scripts/python.exe -m pytest backend/fire/tests -q
```

Python 3.12 in `.venv`, called by path — a bare `python` here is the system
3.14 with none of the geospatial wheels. Deps in
`backend/fire/requirements.txt`.

## Backend branch integration

The backend API described below is included from routing-backend. The fire engine's HTTP integration remains separate.

## Backend

`backend/` — FastAPI service that serves fire-risk GeoJSON, shelters, geocoding,
and route plans (units: **minutes** and **kilometers**, geometry **EPSG:4326**).

### Run

```bash
# from the repo root, using the project venv
.venv/Scripts/uvicorn backend.main:app --reload
```

Interactive API docs at `http://localhost:8000/docs` (Pydantic models give
request/response validation for free).

### Endpoints

| Method | Path | Status |
|---|---|---|
| GET | `/health` | ok + service name |
| GET | `/fire?lat=&lon=&t=` | fire-risk GeoJSON (demo scenario in `demo_data/fire.json`) |
| GET | `/shelters` | all demo shelters (`demo_data/shelters.json`) |
| POST | `/geocode` | hardcoded demo addresses → coords; echoes coords if given |
| POST | `/plan` | `{origin, household, t}` → route JSON (Milestone 2+) |
| GET | `/scenario/{t}` | precomputed replay snapshots (Milestone 7) |
| POST | `/chat` | agent endpoint, LLM key stays server-side (Milestone 8) |

`/plan`, `/scenario/{t}`, and `/chat` currently return **501 Not Implemented**
until their milestones land.

CORS is enabled for `http://localhost:5173` and `http://localhost:3000`.

### Tests

```bash
# from the repo root
.venv/Scripts/python -m pytest
```

## API integration update (supersedes the endpoint status above)

The HTTP API now consumes the merged fire engine. See
[backend/api/README.md](backend/api/README.md) for current setup and behavior.
GET /fire supports demo, live (5-minute cache with last-good fallback), and
replay modes. GET /scenario/{t} serves the four published fire replay frames.
Fire payloads retain their exact contract and additive fields.

Routing currently uses isolated synthetic road/shelter fixtures under
backend/routing/demo/. It still needs a real road cache and approved shelters;
the default origin has no eligible route under the published demo hazards.
The API returns 422 in that case. POST /chat awaits the frontend-owned agent.

Run ./.venv/Scripts/python.exe -m pytest -q to check the integration offline.
