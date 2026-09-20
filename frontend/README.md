# Ignis frontend

Run `npm install`, then `npm run dev` from `frontend/`. The backend must be running on port 8000. Open the Vite URL. Both localhost and 127.0.0.1 work through the development proxy: browser requests go to `/api/fire` and `/api/plan`, and Vite forwards them to `http://127.0.0.1:8000/fire` and `/plan`.

`npm run build` produces `dist/`; `npm run lint` checks source. Production hosting must proxy `/api` to the backend, or build with `VITE_API_BASE_URL` set to the backend URL and configure backend CORS for the frontend origin. No credentials belong in Vite environment variables.

## Milestone status

1–3: map, fixture overlays, and route comparison implemented.

4: frontend API integration implemented, defaulting to Backend demo. Both requests share `mode` and `t=T0`. Planning uses the backend's supported demo origin (39.76, -121.62), one occupant, a vehicle, and no pet/accessibility requirements. Origin/household editing is not part of this checkpoint. Routes, destination coordinates and attributes, metrics, warnings, timestamps, and cache headers come from the backend. The backend still uses synthetic roads and fictional shelters, even with live fire. A real-road milestone completion requires backend data work.

5–8: not started. No chat, extraction, agent, or replay controls are connected.

9: existing styling and offline preview only; full demo rehearsals remain pending.

## Sources and failure behavior

- **Backend demo**: `/fire?mode=demo&t=T0` and `POST /plan` with `mode=demo,t=T0`.
- **Live fire / synthetic roads**: the same requests with `mode=live,t=T0`. Needs server-side FIRMS credentials and upstream connectivity. This does not turn the road/shelter fixtures into real data.
- **Offline bundled demo**: explicit opt-in to local `demo_data/risk_demo.json` and `src/data/plan-demo.json`. Never selected automatically after a failed request. Fire/route fixtures are fictional; the local route fixture is independent of the backend graph.

Loading, refresh and retry states clear previous geometry. A 422 plan response shows the backend's detail and keeps the fire map without routes. Fire failure hides plans. Mismatched fire/plan observation timestamps suppress the plan and request a retry. Source changes abort previous requests, with a 90-second client timeout for slow requests. Failed live refreshes can still return the backend's last-good payload; cache staleness is shown explicitly. Cache age is not observation age. Matching observation timestamps do not prove identical underlying payloads; the backend has no shared snapshot identifier.

Each successful refresh remounts map geometry, including the destination marker. Map layer preferences persist. The server's exposure score is displayed as a score, never a probability: each edge contributes intersection length only in its most severe band; weighted km = 10*h1 + 4*h3 + h6. Recommended cost = travel minutes + 4*weighted km. Fastest and recommended can be identical.

## Live national view

A second tab, `Live · every US fire`, draws `GET /fires`: every fire currently
burning in the contiguous US, each with the same cumulative bands as the
scenario view. Added by Justin alongside the engine change that produced the
endpoint; the scenario view and its components are untouched apart from the
band palette moving to `src/bands.js` so both maps can import it.

The view is built around the things a fire map has to answer at a glance, and
most of them were borrowed from studying mapofire.com: markers sized by the
fire's reported acreage, satellite detections coloured by how old the
observation is (under 12 h / 12-24 h / over 24 h), every timestamp shown as
"7 h ago" with the absolute UTC stamp on hover, and a detail panel per fire
with status, containment, the modeled +1/+3/+6h areas and a "how fresh is
this" block. Selecting a fire sets `?fire=<id>` and the tab title, so a link
opens on that fire.

The basemap is Esri's Light Gray Canvas, base plus labels. It is desaturated
on purpose -- the risk bands and detections should be the only saturated
things on screen. CARTO's `light_all` would be the obvious choice and now
stamps "API KEY REQUIRED" across every tile, which only shows up in a
screenshot.

`/fires` is fetched on first open rather than on mount — it is a live run over
the whole country and takes up to a minute cold, then ~10 s behind the API's
15-minute cache. Stamps are UTC here, not Pacific: the view spans four time
zones and UTC is the clock the satellite passes report in. Payload shape is in
`../demo_data/README.md`.

## Offline preview

`VITE_OFFLINE=true npm run dev` (or build) starts in explicit offline bundled mode with street tiles disabled. All overlay assets are bundled. The street basemap checkbox can independently disable tiles; no street basemap is bundled. Turning off tiles does not disable API calls in Backend demo or live mode.

Protected backend/fire, backend/weather, backend/routing and demo_data files are consumed without edits. Geometry remains GeoJSON [lon, lat]; fuel image bounds use Leaflet [lat, lon]. No household persistence or LLM calls are present.

## Verification of this integration

- `npm test`: API request contracts, source/cache headers, backend error details/status, and invalid JSON handling.
- Local browser + running backend: matching demo/T0 requests, two 12-minute / 9.584-km routes, backend destination attributes, and successful retries.
- A request modified by the browser harness to `has_vehicle=false` exercises the real backend 422 response: no route cards or lines remain, while fire stays visible.
- Browser-injected responses exercise fire 503 failures, stale-cache headers, changed route geometry, and mismatched observation timestamps. Failures never activate bundled fixtures; explicit offline selection does. Mismatched observations suppress routes.
- Checked mobile at 390 px without horizontal overflow.

Live upstream fire availability and a real road network were not validated. These checks cover only Milestone 4 frontend integration, not full demo rehearsals.
