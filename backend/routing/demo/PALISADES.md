# Palisades historical evacuation comparison

This is a fixed January 8, 2025 03:00 Pacific (11:00 UTC) scenario. It is not
current evacuation information. `/demo/palisades` returns the polygons, fire
replay, banner and default coordinates; `/demo/palisades/plan` computes routes
with historical evacuation restrictions applied or ignored.

## Evacuation source

`palisades_evacuation_raw.geojson` preserves the downloaded feature geometry and
source attributes. Added collection metadata records the source, query envelope,
archive timestamp and retrieval timestamp. No boundary was hand-drawn, simplified,
or derived from a burned-area perimeter.

- Publisher: FEMA Region 9, archiving the Cal OES aggregated evacuation feed.
- [Source item](https://www.arcgis.com/home/item.html?id=732dfda3f6dc45418a9d29f559d28943)
- [Feature layer](https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/Operations_Evacuation_Static_Polygon_CA_Historic_Evacuation_Zones_CalOES_R9/FeatureServer/1)
- Query: `EFFECTIVE_DATE_R9 >= TIMESTAMP '2025-01-08 00:00:00' AND EFFECTIVE_DATE_R9 < TIMESTAMP '2025-01-09 00:00:00'`.
- Spatial envelope: `[-118.8, 33.95, -118.4, 34.2]`, EPSG:4326;
  spatial relation intersects, output EPSG:4326 GeoJSON.
- Fields: `OBJECTID,COUNTY,ZONE_NAME,STATUS,EVENT_TYPE,NOTES,EFFECTIVE_DATE_R9`.
- Retrieved object IDs: 4 (order), 5, 6, 7, 8 (warnings).
- The original records have no zone names: the API labels them `Archived area N`
  rather than inventing official zone identifiers.

The archive describes daily 03:00 Pacific backups of the Cal OES feed. Its
archive time is not the original order issuance time, nor a guarantee of all
orders issued later that day. Source notes identify LA County Office of
Emergency Management alerts. Order and warning polygons remain distinct in the
map response. Routing conservatively excludes entry into either category;
a warning is not represented as an official road closure.

## Fire replay

`palisades_fire.json` is the output of the existing, unchanged
`backend.fire.spread.risk_payload`, with:

```python
bbox = (-118.8, 33.95, -118.4, 34.2)
when = datetime(2025, 1, 8, 11, 0, tzinfo=timezone.utc)
```

It uses the default fuel/slope settings and was checked with the fire team's
contract validator. The whole demo road area is within this requested model
extent. The generator used temporary FIRMS/LANDFIRE cache directories; no
fire-team files or shared demo_data were modified. Timestamps in `data_as_of`
identify the actual observations; `generated_at` is the replay generation time.
Do not substitute the final NIFC burned perimeter for current fire or evacuation
orders. Rebuilding this payload requires the engine's upstream services and
FIRMS key; serving the bundled payload requires neither.

## Roads and destination

`../osm/palisades.graphml` is an OSMnx drive network centred on
`34.04, -118.515`, radius 6,000 metres: 3,662 nodes and 9,960 directed edges.
Downloaded during this implementation; the GraphML `created_date` records its
generation timestamp. OSM source attribution: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL.

To rebuild (optional dependency, never needed by serving requests):

```powershell
./.venv/Scripts/python.exe -m pip install -r backend/routing/requirements.txt
./.venv/Scripts/python.exe -m backend.routing.cache_osm --lat 34.04 --lon -118.515 --radius-m 6000 --output backend/routing/osm/palisades.graphml
```

Speeds/travel times are estimates. This is a current road cache, not a reconstruction
of 2025 closures, traffic, turn restrictions or emergency access rules. The default
destination is a road point selected to demonstrate a routing difference, not an
asserted shelter. The historical fire and evacuation snapshot stay fixed in both
toggle states. OFF is explicitly a comparison, never an evacuation recommendation.

Tests in `backend/tests/test_palisades_demo.py` check that the default OFF route
crosses the archived mandatory order, ON avoids the supplied restricted areas,
and both avoid the modeled current-fire and 1-hour regions.
