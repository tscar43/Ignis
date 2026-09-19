# Role Brief: Backend, Routing & Decision Engine

**Project:** Wildfire Evacuation Intelligence Agent
**Your job in one sentence:** Take the geospatial teammate's risk polygons, a road network, and shelters, and return a fastest route and a lower-exposure route with clear metrics, served through a FastAPI backend everyone else calls.

> Geospatial predicts the hazard. You navigate through it. Frontend turns it into a product.

---

## What you own

- FastAPI app (`backend/main.py`) and all HTTP endpoints
- Road network (OpenStreetMap via OSMnx), cached locally
- Geocoding the user's address
- Shelter data and filtering (pets, accessibility)
- Edge risk scoring and route computation
- Route comparison and the structured route JSON
- Replay endpoints that serve precomputed scenario snapshots

## What you do NOT own

- The spread model (Geospatial). You consume their GeoJSON; don't modify the model.
- The map UI and the AI agent's prompts (Frontend). You do host the endpoint the agent runs behind, because the LLM API key must stay server-side.

---

## Inputs you consume (from Geospatial)

```json
{
  "generated_at": "...",
  "data_as_of": { "firms": "...", "weather": "..." },
  "fire_points": { "type": "FeatureCollection", "features": [] },
  "risk_polygons": { "current": {}, "h1": {}, "h3": {}, "h6": {} },
  "summary": { }
}
```

- EPSG:4326 GeoJSON FeatureCollections.
- **Bands are cumulative** (`h6` ⊇ `h3` ⊇ `h1` ⊇ `current`). Score each edge by the **most severe** band it touches.
- Until the real model is ready, use the fake file in `demo_data/`. Never wait on Geospatial.

## Output you produce (to Frontend)

```json
{
  "generated_at": "2026-09-19T14:02:00Z",
  "data_as_of": { "firms": "...", "weather": "..." },
  "origin": { "lat": 39.76, "lon": -121.62, "label": "123 Oak St" },
  "destination": {
    "id": "shelter_03", "name": "Lincoln High School",
    "lat": 39.81, "lon": -121.58,
    "accepts_pets": true, "accessible": true
  },
  "routes": [
    {
      "type": "recommended",
      "geometry": { "type": "LineString", "coordinates": [] },
      "travel_time_min": 24,
      "distance_km": 18.5,
      "exposure": 0.17,
      "exposure_breakdown_km": { "current": 0, "h1": 0, "h3": 0.4, "h6": 2.1 },
      "named_roads": ["Ridge Rd", "Hwy 70"]
    },
    {
      "type": "fastest",
      "geometry": { "type": "LineString", "coordinates": [] },
      "travel_time_min": 18,
      "distance_km": 14.8,
      "exposure": 0.73,
      "exposure_breakdown_km": { "current": 0, "h1": 1.2, "h3": 3.0, "h6": 1.1 },
      "named_roads": ["Hwy 9"]
    }
  ],
  "warnings": ["Fastest route crosses the modeled 1-hour risk region."]
}
```

Why the extra fields: `named_roads` and `exposure_breakdown_km` let the AI say "Highway 9 crosses about 1.2 km of the 1-hour region" instead of vague claims. `warnings` gives the UI a banner. **Agree on units now:** minutes and kilometers.

---

## Endpoints (suggested)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Sanity check |
| POST | `/geocode` | Address → lat/lon |
| GET | `/fire?lat=&lon=&t=` | Returns Geospatial's output (live or replay time `t`) |
| POST | `/plan` | `{origin, household, t}` → route JSON above |
| GET | `/shelters` | All shelters for the map |
| GET | `/scenario/{t}` | Precomputed replay snapshot (fire + routes) for T0/+1/+3/+6 |
| POST | `/chat` | Hosts the agent loop Frontend writes; keeps the LLM key server-side |

Enable **CORS** for the frontend dev server on day one. It's the most common "why is nothing working" moment at integration.

The agent calls tools that map to these (`get_fire_data`, `find_shelters`, `calculate_routes`, `compare_routes`). Make each one a plain Python function first, then wrap it in an endpoint, so the agent can call the function directly.

---

## Road network

- `osmnx.graph_from_point(center, dist=..., network_type="drive")` for the demo area.
- Add speeds and travel times (`add_edge_speeds`, `add_edge_travel_times`).
- **Cache it** with `save_graphml` and load from disk. Overpass is rate-limited and slow; don't hit it during judging.
- Snapping origin/destination: `nearest_nodes`. On an unprojected graph this needs scikit-learn installed; or project the graph first.
- Convert edges to a GeoDataFrame (`graph_to_gdfs`) for spatial joins with the risk polygons.

## Geocoding

Use Nominatim (respect its usage policy: low request rate, a real User-Agent) or hardcode the demo address → coordinates. **For the demo, hardcode.** A geocoder failure on stage is avoidable.

## Shelters

Hardcode 4–6 realistic shelters in `demo_data/shelters.json` with `accepts_pets`, `accessible`, `capacity`. Filter by household constraints before routing. Route to the best 2–3 candidates and pick by cost.

---

## Scoring

### MVP (get this working first)
Delete edges intersecting `current` or `h1`, then route by travel time. That's the "avoid the fire" version.

### Target version: cost = time + λ × exposure

```
C_e = T_e + λ × R_e
```

Per edge `e`:
- `T_e` = travel time
- `R_e` = length inside each band × band weight

| Band touched | Suggested weight |
|---|---|
| current | remove edge (hard block) |
| h1 | 10 |
| h3 | 4 |
| h6 | 1 |

Compute with a spatial join of edges against each band (use the GeoDataFrame spatial index, not a Python loop over every edge). Store `risk_cost` as an edge attribute, then `shortest_path(G, o, d, weight="risk_cost")`.

**Two routes:**
- `fastest` = weight `travel_time`
- `recommended` = weight `risk_cost`

If they're identical, say so ("the fastest route is also lowest-exposure") rather than inventing a difference.

**Route exposure score (0–1):** normalize the weighted exposure length by route length, clamp to [0,1]. Document the formula in the README; judges may ask.

**Tune λ** on the demo scenario so the recommended route is noticeably safer but not absurdly long. Show one or two λ values if asked.

### Upgrade if time allows: time-aware exposure
A car reaches an edge at time `t`. Crossing the h3 band at minute 10 is less dangerous than crossing the h1 band at minute 50. Compare cumulative drive time at each edge with the band's time. This is a strong judge-facing detail even if simplified.

---

## Replay mode

Precompute snapshots for T0, +1h, +3h, +6h and save them as JSON. The demo should load files, not recompute live. Recompute only if it's fast and stable.

---

## Suggested stack

`fastapi`, `uvicorn`, `pydantic` (model the contracts; free validation + docs at `/docs`), `osmnx`, `networkx`, `geopandas`, `shapely`, `httpx`.

## Files you own

```
backend/main.py
backend/routing/roads.py     # load/cache graph, snapping
backend/routing/risk.py      # edge risk from polygons
backend/routing/routes.py    # fastest, recommended, compare
backend/shelters/shelters.py
demo_data/shelters.json
demo_data/graph.graphml      # cached network
```

---

## Milestones (in order)

1. FastAPI running with `/health`, CORS on, Pydantic models for both contracts.
2. Route A → B on the cached graph, returned as GeoJSON LineString. **Send to Frontend.**
3. Route around a manually drawn polygon.
4. Swap in Geospatial's fake `demo_data` polygons, then the real ones.
5. Fastest vs. recommended with metrics and `exposure_breakdown_km`.
6. Shelter filtering by household constraints.
7. `/scenario/{t}` replay snapshots.
8. Host `/chat` for Frontend's agent.
9. Optional: time-aware exposure.

**Rule:** no advanced integration until Geospatial, Backend, and Frontend each have their foundation working.

---

## Out of scope

Live traffic simulation, congestion modeling (stretch only), live evacuation orders ingestion, multi-city support.

---

## Questions judges will ask you

- **"Won't everyone get sent down the same road?"** Yes, that's a real risk. The fix is to distribute recommendations across viable routes or penalize bottleneck roads; it's on our roadmap.
- **"How did you choose λ and the band weights?"** Tuned on the scenario to trade a few minutes for much lower exposure; show the comparison.
- **"What if the recommended road is officially closed?"** Official closures and orders override us. In production we'd ingest closure feeds; in the demo we can manually block edges.
- **"What if cell service drops?"** The plan and route could be saved offline in advance (stretch).
- **"Why not just use Google Maps routing?"** Google routes around current closures; we route around where the fire is projected to be, and we expose the exposure metric that drove the decision.
