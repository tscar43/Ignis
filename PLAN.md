# Backend status and remaining handoff

Completed:

- Fire API: unchanged engine payloads, offline demo/replay, live TTL cache and
  last-good fallback, with source/staleness headers.
- Routing: cached Paradise and Palisades roads; quickest eligible primary route,
  optional distinct alternative; current-fire/1-hour exclusions; segment-level
  exposure accounting and household filtering.
- Shelters: local FEMA catalogue, freshness/policy checks and reviewed entrances.
  Demo destinations remain explicitly fictional; the Palisades comparison point
  is not a shelter.
- Palisades historical demo: official archived order/warning polygons for
  January 8, 2025, matching engine replay, banner metadata, and an orders toggle
  restricted to the historical comparison endpoint.
- Deployment checks: configurable frontend CORS, `/health` for liveness and
  `/ready` for offline demo datasets. Dataset failures return 503.

Frontend handoff:

- Consume `/demo/palisades` and `/demo/palisades/plan`; render banner, polygons,
  optional route alternatives and comparison labels. See `backend/api/README.md`.
- The frontend teammate owns the AI agent. `/chat` remains its integration stub.
- `/geocode` supports the documented demo address only; map/coordinate input is
  supported by planning. Do not advertise general address lookup yet.

Live capabilities still require externally verified data:

- Fresh operator-maintained evacuation snapshots; no automatic live order feed.
- OPEN shelters with reviewed access and known required household policies.
- Traffic, official closures, turn restrictions and real available beds are not
  integrated. Modeled route eligibility is not a certification of safety.

`/scenario/{t}` continues to serve the Camp Fire replay payload unchanged.
Fire-team files, weather, contracts and shared demo_data remain unmodified.
