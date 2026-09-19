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

## Live, not replay

`risk_demo.json` is fake and `risk_replay.json` is a 2018 fire. For a live
feed call the engine directly, no file involved:

    from backend.fire.spread import risk_payload
    risk_payload()            # newest VIIRS pass + GOES ABI frame, HRRR wind
