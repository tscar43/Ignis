# demo_data — FAKE fire data

`risk_demo.json` is **hand-drawn, not modeled.** No FIRMS, LANDFIRE, or wind data
went into it. It exists so Backend and Frontend can build against the real shape
of the payload today and swap in the live engine later with no code changes.

Regenerate with:

    ./.venv/Scripts/python.exe backend/fire/make_demo_data.py

It's deterministic (fixed seed, frozen timestamps), so it re-writes byte-identical
and diffs stay clean.

## What's in it

Fictional fire near Concow / Paradise, CA (Butte County), 4 hotspots, wind 35 km/h
pushing **toward 240° (southwest)**.

```
generated_at              ISO8601 Z
data_as_of.firms          when the hotspots were observed  <- show this in the UI
data_as_of.weather        when the wind was observed
fire_points               FeatureCollection of Points; properties: confidence, frp, acq_time
risk_polygons.current     FeatureCollection of Polygons
risk_polygons.h1          "
risk_polygons.h3          "
risk_polygons.h6          "
summary                   small object; this is what the LLM reads
```

## Guarantees you can code against

- **EPSG:4326, `[lon, lat]`** order, standard GeoJSON. Not lat/lon.
- **Bands are cumulative:** `h6 ⊇ h3 ⊇ h1 ⊇ current`. Verified at generation time.
  Don't union them yourself, and don't expect h3 to be a ring around h1.
- A band can be a **MultiPolygon-worth of features** (separate hotspots, and holes
  carved by non-burnable barriers). Iterate `features`, don't assume one.
- Every band feature carries `properties.band` (`current` / `h1` / `h3` / `h6`).
- `summary.area_km2` matches the polygons, in km².
- `summary.wind_toward_deg` is the direction fire is pushed **toward**, already
  flipped from the meteorological "wind from" convention. Don't flip it again.

## What will change when the real engine lands

Values, polygon count, and vertex count — not keys, not units, not CRS. If you
need a key that isn't here, ask before assuming it; `contracts/` is shared.

---

## The other files here

`risk_replay.json` — four real frames (T+0/1/3/6 h) from the 2018 Camp Fire,
for a scrubber. Same contract as `risk_demo.json` plus a `replay` block with
`offset_h` and `at`. Generated from real FIRMS, LANDFIRE and reanalysis data,
not hand-drawn:

    ./.venv/Scripts/python.exe -m backend.fire.spread --replay

Each frame re-seeds from whatever satellite pass was newest at that moment, so
`data_as_of.firms` goes stale across the frames on purpose — by T+6 h the
newest observation is 4.3 h old. Show that timestamp in the UI.

`fuel_overlay.png` + `fuel_overlay.json` — LANDFIRE fuel families as a map
overlay. Rendered in EPSG:4326 so it drops straight onto a web map; the JSON
carries `bounds` in Leaflet's `[[south, west], [north, east]]` order, plus a
colour legend. Display only, and deliberately coarser than it could be:

    ./.venv/Scripts/python.exe -m backend.fire.landfire --overlay

`palisades_comparison.png` + `palisades_nifc_perimeter.geojson` — how the
engine scored against the January 2025 Palisades Fire, beside the
FARSITE-class elliptical model and the fire's observed footprint. The GeoJSON
is NIFC's final perimeter, 23,448 acres, used for context in the figure and
not by the engine. Numbers and caveats are in `backend/fire/FINDINGS.md`:

    ./.venv/Scripts/python.exe -m backend.fire.palisades

`palisades_replay.json` — the same four windows as GeoJSON, for the frontend's
stepped model-vs-truth tab. Served unchanged at `GET /palisades`; a static
fixture on purpose, so the tab never waits on FIRMS mid-presentation.

    ./.venv/Scripts/python.exe -m backend.fire.palisades --json

**This one is not a contract payload.** It has no risk bands, no cumulative
nesting and no `summary`, so `contract.validate()` does not apply to it. What
it does share is the CRS convention: every geometry is EPSG:4326, `[lon, lat]`,
coordinates rounded to 5 decimals.

```
fire, generated_at        ISO8601 Z
reseeding, perimeter      the two sentences the UI must show; see below
r0_m_per_min              fitted spread rate per model, m/min
length_to_breadth         ellipse L:B at the fit window's wind
colors                    per-model hex, carried from palisades.py's palette
windows[]                 one per pass, in time order
  seed_at, validate_at    real VIIRS overpass times
  role                    "fit" (window 1) | "scored"
  gap_h                   hours from seed to validation
  wind_kmh, wind_toward   wind at the seed pass; toward, already flipped
  seed_km2                area of the seed footprint
  observed_km2            area actually detected by validate_at
  models[name]            r0, predicted_km2, iou, iou_growth
  seed                    FeatureCollection of Polygons
  observed                "
  predictions[name]       "
```

Two things a consumer must not get wrong, which is why they ship as prose in
the payload rather than as a note here:

- **Window 1 is the calibration window.** R0 is fitted on it. Its IoU restates
  that fit and is not a score — label it, never headline it.
- **Every window re-seeds from observed truth**, not from the previous
  window's prediction. Four independent ~12 h forecasts, not one 48 h run.

## Live, not replay

`risk_demo.json` is fake and `risk_replay.json` is a 2018 fire. For a live
feed call the engine directly, no file involved:

    from backend.fire.spread import risk_payload
    risk_payload()            # newest VIIRS pass + GOES ABI frame, HRRR wind

## Every fire in the country

`risk_payload()` answers for one bbox. `GET /fires` answers for all of CONUS:

    {
      "generated_at": "2026-09-20T01:29:58Z",
      "bbox": [-125.0, 24.4, -66.9, 49.4],
      "incidents_found": 310,          // clusters in the newest FIRMS sweep
      "incidents_active": 544,         // still burning: see `excluded`
      "incidents_modelled": 12,        // the rest are below the cut, not missing
      "named_by_wfigs": 13,            // clusters matched to a NIFC incident
      "excluded": {                    // detected, then deliberately left out
        "static heat source": 60,      //   flares, refineries, landfills
        "contained": 1                 //   NIFC calls it 100% contained
      },
      "fires": [ { ...a whole payload..., "incident": {...} } ],
      "failed": [ { ...incident..., "error": "HTTPError: ..." } ]
    }

Every entry of `fires` is one complete payload exactly as documented above --
same keys, same `[lon, lat]`, same cumulative bands -- with one block added:

    "incident": {
      "id": "37.60N119.61W",           // cluster centroid to 0.01 deg
      "lon": -119.6149, "lat": 37.5992,
      "bbox": [-119.79, 37.46, -119.42, 37.74],
      "detections": 236,
      "frp_mw": 2804.3,                // total radiative power
      "newest_pass": "2026-09-19T21:10:00Z",

      // present only when the cluster matched a NIFC WFIGS incident
      "name": "Dome",
      "irwin_id": "{AACFD673-4C1B-4CDF-B9DD-128E34BD7272}",
      "acres": 2384,                   // NIFC's number, not ours
      "contained_pct": 15,
      "place": "Mariposa County, CA",  // somewhere a person can picture
      "agency": "NPS",
      "discovered": "2026-09-15T15:28:00Z",
      "updated": "2026-09-20T00:32:21Z",   // when the agency last touched it
      "has_perimeter": true,           // seeded from the official perimeter
      "source": "NIFC WFIGS"
    }

So a client that can draw `/fire` can draw `/fires` by looping. Three things
to expect:

- `failed` is often non-empty. A dozen fires is a dozen chances for LANDFIRE,
  HRRR or GOES to time out, and one fire failing does not fail the run.
- The list is not all the clusters. Contained fires, incidents nobody has
  updated in a week, and persistent industrial heat are excluded outright and
  counted in `excluded`. Of what remains, fires NIFC has an incident record
  for come first, then the brightest of the rest -- mostly agricultural
  burning, which looks identical to a wildfire from orbit.
- `data_as_of.firms` can be over a day old on a real fire, and that is not a
  bug to filter out. Clouds and orbit gaps mean roughly a third of active
  incidents have no clear overpass in the last 24 h. Show the age.
- The NIFC block is absent, not null, when nothing matched. Check for `name`
  before reading `acres`, and fall back to `id`, which is always there.
