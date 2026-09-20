# Backend development plan after fire-engine integration

1. Completed: consume the merged engine contract directly, without editing the
   engine, weather modules, contracts, or published demo_data.
2. Completed: live /fire with a five-minute TTL, concurrent refresh protection,
   last-good fallback, failure retry throttling, and cache metadata in headers.
3. Completed: serve published demo and all four replay frames unchanged.
4. Completed: adapt routing to dictionary payloads; move synthetic fixtures into
   backend/routing/demo; test API/cache behavior and the existing engine offline.
5. Next: prepare a real cached OSM network and approved shelter catalogue under
   backend-owned paths. The existing synthetic graph has no eligible route from
   the default origin under the published demo hazards. Validate coverage and
   endpoint snapping before tuning exposure costs.
6. Next: precompute fire-plus-route replay snapshots for agreed origins and
   household profiles. Current /scenario responses contain fire data only.
7. Next: integrate the frontend-owned agent behind /chat; keep secrets server-side.
8. Optional: closure feeds, time-aware exposure, shared/persistent live cache.

Work stays on routing-backend, where origin/main was already merged. The Git
index contains pre-existing staged deletions; the backend commit uses explicit paths and leaves unrelated staged deletions
untouched. Obsolete backend stub tests are replaced by the integration suite.
