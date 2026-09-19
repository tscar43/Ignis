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
