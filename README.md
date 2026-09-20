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

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/ready` | validates every bundled offline demo, including each replay offset |
| GET | `/fire` | `mode=demo\|replay\|live`, `t=T0\|H1\|H3\|H6` |
| GET | `/fires` | national sweep, every active CONUS fire |
| GET | `/palisades` | model-vs-truth fixture, never hits the network |
| GET | `/scenario/{t}` | one replay frame, no routes |
| GET | `/shelters` | `source=demo\|fema` |
| GET | `/shelters/catalog` | with per-shelter access report |
| GET | `/evacuations` | `mode`, optional `lat`/`lon` |
| POST | `/plan` | route plan; four live-mode gates, see the API guide |
| POST | `/geocode` | two bundled demo addresses only |
| POST | `/chat` | Claude-backed evacuation assistant |
| GET | `/history` | which fires have stored history (TigerData) |
| GET | `/history/{fire_id}` | burn intensity and modelled area over time |
| GET | `/demo/palisades` | demo metadata |
| POST | `/demo/palisades/plan` | `apply_evacuation_orders` toggles the comparison |

Routing runs over a cached OpenStreetMap drive network (Paradise: 1,279 nodes,
2,863 directed edges; Palisades has its own). Requests are offline; the
synthetic fixture is still reachable through `IGNIS_GRAPH_PATH`. Shelters are
fictional demonstration locations placed on the road network.

CORS is enabled for `http://localhost:5173` and `http://localhost:3000`.
Details and the live-mode 503 gates: [backend/api/README.md](backend/api/README.md).

### Optional credentials

Both are optional and independent. Without either, the feature returns 503
with an actionable message and nothing else is affected.

| Variable | Enables |
|---|---|
| `FIRMS_MAP_KEY` | live satellite detections (`mode=live`, `/fires`) |
| `ANTHROPIC_API_KEY` | `POST /chat` |
| `TIGERDATA_URL` | `/history` (TimescaleDB); seed with `python -m backend.api.timeseries seed` |

Copy `.env.example` to `.env` and fill in what you need. On Windows PowerShell
do **not** append with `>>` — 5.1 writes UTF-16 and silently corrupts the file.

### The assistant

`POST /chat` takes `{messages, mode}` and returns `{reply, plan}`. It has one
tool, and that tool calls the `/plan` endpoint function itself rather than a
copy of it, so the assistant inherits every gate `/plan` has and cannot
describe a route the router would refuse. `plan` is a full `PlanResponse` when
it routed during that turn, which the map draws.

### Tests

```bash
.venv/Scripts/python -m pytest
```
