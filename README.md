# Ignis — Wildfire Evacuation Intelligence Agent

Predicts where a wildfire is going, and routes households out of its path.
Geospatial feeds risk polygons into a FastAPI backend that computes a fastest
and a lower-exposure route to an open shelter; the frontend turns that into a
map + AI briefing.

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
