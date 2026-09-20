# Ignis frontend

Daniel owns this implementation under the frontend / AI-agent role brief. Start with `npm install`, then `npm run dev` from this directory. `npm run build` produces `dist/`; `npm run lint` checks the source.

## Milestones

1. Implemented: Leaflet map centered on Concow / Paradise.
2. Implemented: fire fixtures imported read-only from `../demo_data/risk_demo.json`, cumulative bands rendered h6 → h3 → h1 → current, hotspots, wind, fuel overlay, layer toggles, legend and observation timestamps.
3. Implemented: route comparison with fictional plan JSON in `src/data/plan-demo.json`. No route fixture exists in `demo_data/`; this local fixture leaves that owned directory untouched. Geometry is illustrative, not road-network output. Values are display fixtures, not calculated route metrics.
4. Pending: Backend `/fire` and `/plan` endpoint URL, request contract, and real routing service. There is no API entry point in this checkout. Verify real FIRMS points and a real backend route on one map before starting milestone 5.
5–9. Pending in the requested order: stub chat, extraction and editable chips, backend agent tools, scenario replay, polish and three full demo rehearsals. No AI connection has been added ahead of the real-route checkpoint.

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

Run `VITE_OFFLINE=true npm run dev` or `VITE_OFFLINE=true npm run build` to disable external map tiles by default. All fire, route and fuel assets are bundled locally. The street basemap checkbox can also disable tiles. There is no bundled street map: overlays remain available on a neutral background offline. Tile failures display a visible notice.

The demo is explicitly fictional, shows dated observations in Pacific time, and must not be used for navigation. No household input, API keys, storage or LLM calls are present. Basemap tiles, when enabled, request OpenStreetMap resources.

## Integration handoff

The map accepts `fire`, `plan`, `layers`, and `basemap` props; the route panel accepts `plan`. These consume the brief's payload shape. Replace the bundled data only after confirming the actual Backend contract. Do not silently fall back to fictional routes when live requests fail. Shelter map position currently comes from the recommended demo line's endpoint; live shelter coordinates need to be confirmed with Backend. Fuel bounds use Leaflet `[lat, lon]` order; all route/fire geometry remains GeoJSON `[lon, lat]`.

## Browser verification

Checked the rendered map, projected-layer toggle, fuel image overlay, offline notice, both route cards, persistent disclaimer, and a 390 px mobile viewport with no horizontal overflow. Browser console showed no application errors. These checks are not the full demo rehearsals required by milestone 9.
