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
