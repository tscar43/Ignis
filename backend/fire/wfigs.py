"""NIFC WFIGS: the official incident record, as a name and as a footprint.

FIRMS says a 375 m pixel was hot at 37.60N 119.61W. WFIGS says that is the
Dome fire, 2384 acres, 15% contained, and here is the perimeter an IR flight
mapped. Two things come out of that, and both matter more than they look:

- a fire with a name is a fire a person can act on, and an IRWIN id is the
  key every other agency feed is joined on;
- a perimeter is the real burned footprint. Seeding from satellite pixels
  alone puts scattered 375 m squares where the fire is *hottest*, which is
  not where its edge is. The union of the two is the honest seed: the
  perimeter says how big, the fresh detections say how far it has run since
  the flight that mapped it.

So this is not a competing source. It is the ground truth our projection sits
on top of. Anonymous ArcGIS REST, no key.

Portal: https://data-nifc.opendata.arcgis.com/
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from shapely import STRtree
from shapely.geometry import box, shape

BASE = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services"
POINTS = "WFIGS_Incident_Locations_Current"
PERIMETERS = "WFIGS_Interagency_Perimeters_Current"

# 'WF' is a wildfire; 'RX' is a prescribed burn somebody lit on purpose and
# does not want projected onto an evacuation map.
WILDFIRE = "WF"

# How far a cluster may sit from an incident point and still be that incident,
# when there is no perimeter to test against. A WFIGS point is the reported
# origin, not the centroid, so on a fire that has run for a day the detections
# are legitimately kilometres away -- but only in proportion to the fire. A
# fixed 15 km radius put three Los Angeles County brush calls on industrial
# heat over the harbour, because in a dense county something is always within
# 15 km. The bound scales with the reported size instead.
MATCH_MIN_KM = 2.0
MATCH_MAX_KM = 15.0
MATCH_RADII = 3.0  # how many fire radii out a detection may still belong

# ponytail: the service caps a response at 2000 features and this does not
# page. CONUS carries ~350 current wildfires, so the cap is 5x clear; add
# `resultOffset` paging if that ever stops being true.
MAX_FEATURES = 2000

# "Current" in the service name means the current *season*, not currently
# burning: 215 of 342 CONUS records were reported more than two weeks ago and
# 90 more than two months ago. The obvious close-out fields do not help --
# FireOutDateTime, ControlDateTime and ContainmentDateTime are null on every
# single record in this layer. What is left is containment and the record's
# own last-modified stamp: an incident somebody is still working gets touched
# daily. A big western fire legitimately burns for months, so age alone is not
# the test -- Border 2 was reported 65 days ago, is 74% contained, and was
# updated today.
STALE_AFTER_DAYS = 7


@dataclass(frozen=True)
class Record:
    """One WFIGS incident: what it is called, and what is known about it."""

    name: str
    irwin_id: str
    lon: float
    lat: float
    acres: float | None = None
    contained_pct: int | None = None
    discovered: str | None = None
    modified: str | None = None  # when the agency last touched the record
    county: str | None = None
    state: str | None = None  # POOState arrives as "US-CA"
    agency: str | None = None
    perimeter: dict | None = None  # GeoJSON geometry, EPSG:4326

    @property
    def place(self) -> str | None:
        """"Mariposa County, CA" -- somewhere a person can picture.

        37.60N 119.61W is precise and unreadable. The county is the unit
        evacuation orders are actually issued in.
        """
        state = (self.state or "").removeprefix("US-")
        if self.county and state:
            return f"{self.county} County, {state}"
        return self.county or state or None

    @property
    def active(self) -> bool:
        """Is this fire still going, by the agency's own account?

        Fully contained means the line is closed around it. It can still
        smoulder for weeks and VIIRS will keep seeing it, which is how a
        50,000-acre July fire ends up on a map of what is burning tonight.
        """
        if (self.contained_pct or 0) >= 100:
            return False
        return self.age_days is None or self.age_days <= STALE_AFTER_DAYS

    @property
    def age_days(self) -> int | None:
        """Days since the agency last updated this record."""
        if self.modified is None:
            return None
        when = datetime.strptime(self.modified, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).days

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "irwin_id": self.irwin_id,
            "acres": self.acres,
            "contained_pct": self.contained_pct,
            "discovered": self.discovered,
            "updated": self.modified,
            "place": self.place,
            "agency": self.agency,
            "has_perimeter": self.perimeter is not None,
            "source": "NIFC WFIGS",
        }


def _stamp(epoch_ms) -> str | None:
    """ArcGIS dates are epoch milliseconds, UTC."""
    if epoch_ms in (None, ""):
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _query(service: str, bbox, fields: str, where: str) -> list[dict]:
    """Features of `service` intersecting `bbox`, as GeoJSON.

    `f=geojson` rather than `f=json`: esriJSON rings are ordered by winding
    direction to mark holes, and shapely reads GeoJSON directly, so asking the
    server for the format we already parse saves a converter nobody wants to
    maintain.
    """
    west, south, east, north = bbox
    response = httpx.get(f"{BASE}/{service}/FeatureServer/0/query", timeout=120,
                         params={
                             "where": where,
                             "outFields": fields,
                             "geometry": f"{west},{south},{east},{north}",
                             "geometryType": "esriGeometryEnvelope",
                             "inSR": 4326, "outSR": 4326,
                             "spatialRel": "esriSpatialRelIntersects",
                             "returnGeometry": "true",
                             "resultRecordCount": MAX_FEATURES,
                             "f": "geojson",
                         })
    # A throttled ArcGIS answers 200 with an HTML error page, and .json() then
    # raises JSONDecodeError at "line 1 column 1", which names neither the
    # service nor the reason.
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(
            f"WFIGS {service}: {response.status_code}, "
            f"not JSON: {response.text.strip()[:160]}") from None
    if "features" not in body:
        raise RuntimeError(f"WFIGS {service}: {str(body)[:200]}")
    return body["features"]


def fetch(bbox) -> list[Record]:
    """Current wildfire incidents in `bbox`, perimeters attached where mapped.

    Two queries, joined on the IRWIN id: the point layer carries the
    attributes for every reported fire, the perimeter layer only covers fires
    somebody has actually mapped. A perimeter with no matching point still
    comes back as a record -- it is a real fire either way.
    """
    perimeters = {}
    for feature in _query(
            PERIMETERS, bbox,
            "poly_IncidentName,poly_IRWINID,poly_GISAcres,attr_PercentContained,"
            "attr_ModifiedOnDateTime_dt",
            f"attr_IncidentTypeCategory='{WILDFIRE}'"):
        if feature.get("geometry"):
            perimeters[feature["properties"]["poly_IRWINID"]] = feature

    records, matched = [], set()
    for feature in _query(
            POINTS, bbox,
            "IncidentName,IrwinID,IncidentSize,PercentContained,"
            "FireDiscoveryDateTime,ModifiedOnDateTime_dt,"
            "POOCounty,POOState,POOProtectingAgency",
            f"IncidentTypeCategory='{WILDFIRE}'"):
        point, attributes = feature.get("geometry"), feature["properties"]
        if not point:
            continue
        irwin = attributes["IrwinID"]
        matched.add(irwin)
        records.append(Record(
            name=(attributes.get("IncidentName") or "unnamed").title(),
            irwin_id=irwin,
            lon=point["coordinates"][0], lat=point["coordinates"][1],
            acres=attributes.get("IncidentSize"),
            contained_pct=attributes.get("PercentContained"),
            discovered=_stamp(attributes.get("FireDiscoveryDateTime")),
            modified=_stamp(attributes.get("ModifiedOnDateTime_dt")),
            county=attributes.get("POOCounty"),
            state=attributes.get("POOState"),
            agency=attributes.get("POOProtectingAgency"),
            perimeter=(perimeters.get(irwin) or {}).get("geometry")))

    for irwin, feature in perimeters.items():
        if irwin in matched:
            continue
        attributes = feature["properties"]
        centroid = shape(feature["geometry"]).centroid
        records.append(Record(
            name=(attributes.get("poly_IncidentName") or "unnamed").title(),
            irwin_id=irwin, lon=centroid.x, lat=centroid.y,
            acres=attributes.get("poly_GISAcres"),
            contained_pct=attributes.get("attr_PercentContained"),
            modified=_stamp(attributes.get("attr_ModifiedOnDateTime_dt")),
            perimeter=feature["geometry"]))
    return records


def _km_apart(lon1, lat1, lon2, lat2) -> float:
    """Flat-earth distance, which is fine over the ~15 km this compares."""
    mean_lat = math.radians((lat1 + lat2) / 2)
    return math.hypot((lon2 - lon1) * math.cos(mean_lat), lat2 - lat1) * 111.32


def _reach_km(record: Record) -> float:
    """How far this fire's detections can plausibly sit from its reported origin.

    A 30-acre fire is about 200 m across; it cannot be the source of a hotspot
    12 km away, however close it is in a list. Unknown acreage gets the floor.
    """
    if not record.acres:
        return MATCH_MIN_KM
    radius_km = math.sqrt(record.acres * 4046.86 / math.pi) / 1000
    return min(MATCH_MAX_KM, max(MATCH_MIN_KM, MATCH_RADII * radius_km))


def match(incidents, records: list[Record]) -> dict[str, Record]:
    """{incident.id: Record} for the clusters WFIGS knows about.

    A perimeter that intersects the cluster's own box wins outright -- that is
    containment, not proximity -- and among several, the smallest, because the
    specific fire beats the old 300,000-acre burn scar its detections happen to
    sit inside. Otherwise the nearest reported origin within that fire's own
    plausible reach (`_reach_km`), largest first so a real incident is not
    stolen by a quarter-acre call reported next to it. Clusters with no match
    keep their coordinate id: plenty of real fires are seen from orbit before
    anyone files them, and a wrong name is worse than no name.
    """
    ranked = sorted(records, key=lambda r: -(r.acres or 0))
    mapped = [r for r in records if r.perimeter is not None]
    shapes = [shape(r.perimeter) for r in mapped]
    # Built once: this runs against every cluster in the country, and a
    # perimeter is parsed from GeoJSON into shapely exactly one time.
    tree = STRtree(shapes) if shapes else None

    out = {}
    for incident in incidents:
        footprint = box(*incident.bbox)
        hit = None
        if tree is not None:
            candidates = tree.query(footprint, predicate="intersects")
            if len(candidates):
                hit = mapped[min(candidates, key=lambda i: shapes[i].area)]
        if hit is None:
            near = [(
                _km_apart(incident.lon, incident.lat, r.lon, r.lat), -(r.acres or 0), r)
                for r in ranked]
            near = [item for item in near if item[0] <= _reach_km(item[2])]
            hit = min(near, key=lambda item: item[:2])[2] if near else None
        if hit is not None:
            out[incident.id] = hit
    return out


if __name__ == "__main__":
    from . import national

    found = fetch(national.CONUS)
    mapped = [r for r in found if r.perimeter is not None]
    print(f"{len(found)} current wildfires in CONUS, {len(mapped)} with a perimeter\n")
    for record in sorted(found, key=lambda r: -(r.acres or 0))[:12]:
        print(f"  {record.name:<28} {record.acres or 0:>10,.0f} ac  "
              f"{'' if record.contained_pct is None else str(record.contained_pct) + '%':>4}  "
              f"{'perimeter' if record.perimeter else ''}")
