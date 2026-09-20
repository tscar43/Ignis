# Local FEMA shelter integration

Source: [FEMA National Shelter System, Shelter Locations layer](https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer/5).
This is a facilities catalogue covering all statuses, not a list of guaranteed
available beds. The local query selects Butte County, California,
`facility_type=SHELTER` and `subfacility_code=GENPOPSHEL`. It excludes other
facility/population types. Snapshot retrieval returned 105 general-population
facilities, all CLOSED. Inspect the refreshed snapshot for current results.

## Try locally

```powershell
./.venv/Scripts/python.exe -m backend.shelters.refresh_fema
./.venv/Scripts/python.exe -m uvicorn backend.main:app --reload
Invoke-RestMethod 'http://localhost:8000/shelters/catalog'
Invoke-RestMethod 'http://localhost:8000/shelters?source=fema'
Invoke-RestMethod http://localhost:8000/plan -Method Post -ContentType 'application/json' -Body '{"origin":{"lat":39.76,"lon":-121.62},"shelter_source":"fema"}'
```

`/shelters/catalog` includes all fetched records, source URL, retrieval timestamp,
staleness, and an access report keyed by shelter id. Catalogue inclusion does
not mean open, reachable, or safe. An access report describes the nearest node
in the currently configured road cache; it is not a verified driveway.

`/shelters?source=fema` filters for fresh OPEN records and household constraints.
`/plan` with `shelter_source=fema` additionally requires reviewed entrance access
and a fire-unblocked route. With the downloaded CLOSED records it returns 422,
not a fictional substitute. The default `shelter_source=demo` retains the
existing fictional demo. Fire `mode` and `shelter_source` are independent:
selecting historical fire does not turn the current shelter snapshot into
historical shelter data.

## Data semantics

- `accepts_pets`, `accessible`, and `capacity` can be null. Null is unknown,
  not false or zero. Frontend/agent consumers must display unknown explicitly.
- Only explicit YES/NO wheelchair values become booleans. ADA compliance is
  not substituted for wheelchair accessibility.
- FEMA pet accommodation codes/descriptions are retained as `pet_policy`.
  Their semantics are not assumed to mean pets are accepted; `accepts_pets`
  stays null. Pet-required households therefore cannot select these records.
- `capacity` is nominal `evacuation_capacity`, not available beds. Reported
  population, when present, also limits the candidate count; neither value
  guarantees current availability. Missing capacity is ineligible.
- Only OPEN records fetched within the previous 30 minutes are eligible.
  Future timestamps fail closed. This is a local freshness policy, not a
  guarantee that FEMA's underlying record was updated that recently; this
  layer provides no per-record last-status-update timestamp.
- Catalogue geometry is a facility point, not a confirmed entrance. Coordinates
  are requested in EPSG:4326. Original facility coordinates remain unchanged.

## Entrance review

No entrances have been asserted as verified in the downloaded data. Provide a
separate locally reviewed JSON object with `IGNIS_SHELTER_ENTRANCES_PATH`.
Keys are existing ids such as `fema_172965`. Each value has `lat`, `lon`,
`source_url` (survey/operator or other evidence), and timezone-aware
`verified_at`. Do not use the nearest road node as proof of an entrance.
Only set an override after reviewing the actual vehicle entrance and access.
The file is independent of refreshes, so refreshing FEMA data cannot erase it.
Unknown ids, malformed evidence, and future verification dates are rejected.

Real-source destinations must snap within 50 m to the cached road network.
This engineering cutoff limits an unmodeled gap; it does not prove drivability.
Current-fire intersection is checked along the straight access segment and
at the facility; origin access receives the same intersection check. The
returned route still ends at the road node, and its time/distance omit the
access segment. No driveway, gate, private access, wheelchair path, future
access exposure, or turn-restriction guarantee is inferred from a point.

The existing road cache covers Paradise only; many Butte County facilities
are outside it. An empty eligible list is expected until status, household
requirements, road coverage and entrance review all permit a route.

## Cache operation

`data/fema_butte.json` is a fetched local snapshot with source attribution.
`IGNIS_FEMA_SHELTERS_PATH` can select another snapshot made by this importer.
The refresh command supports `--output`. It uses paginated, bounded-timeout
queries, validates records, and replaces the file only after the full query
succeeds. Errors preserve the previous file. No network requests happen in
`/shelters`, `/shelters/catalog` or `/plan` for shelter data. Missing/invalid
FEMA cache returns 503; expired data remains visible in the catalogue but is
excluded from planning. Refresh explicitly before exercising real-source plans.

Tests use synthetic source responses and injected local files, never network.
