"""Offline tests for the NIFC WFIGS join. No network.

A wrong name is worse than no name: labelling a hotspot "Border 2" when it is
an unrelated refinery flare puts an official-looking incident on an evacuation
map. Both failures these pin were real -- three Los Angeles County brush calls
matched to industrial heat over the harbour 12 km away, and one fire whose
detections split into two clusters modelled and drew twice.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import national, spread, wfigs  # noqa: E402
from backend.fire.firms import Hotspot  # noqa: E402

ACQ = datetime(2026, 9, 19, 20, 1, 17, tzinfo=timezone.utc)


def spot(lon, lat, frp=10.0):
    return Hotspot(lon=lon, lat=lat, confidence="h", frp=frp, acq_time=ACQ,
                   sensor="VIIRS/N20", source="VIIRS_NOAA20_NRT")


def incident(lon, lat, count=2):
    return national.Incident(tuple(spot(lon + 0.001 * i, lat) for i in range(count)))


def ring(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[
        [west, south], [east, south], [east, north], [west, north], [west, south]]]}


def record(name, lon, lat, acres=None, perimeter=None):
    return wfigs.Record(name=name, irwin_id="{" + name + "}", lon=lon, lat=lat,
                        acres=acres, perimeter=perimeter)


def test_arcgis_epoch_milliseconds_become_utc():
    """Milliseconds, not seconds: reading them as seconds lands in 1970."""
    noon = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert wfigs._stamp(noon.timestamp() * 1000) == "2026-09-15T12:00:00Z"
    assert wfigs._stamp(None) is None


def test_a_perimeter_containing_the_cluster_wins():
    fire = incident(-119.61, 37.60)
    hit = wfigs.match([fire], [record("Dome", -119.7, 37.5, 2384,
                                      ring(-119.7, 37.5, -119.5, 37.7))])
    assert hit[fire.id].name == "Dome"


def test_the_specific_perimeter_beats_the_old_burn_scar():
    """A new fire inside last year's 300,000-acre footprint is the new fire."""
    fire = incident(-119.61, 37.60)
    scar = record("Scar", -119.6, 37.6, 300000, ring(-120.5, 37.0, -118.5, 38.5))
    small = record("Dome", -119.62, 37.61, 2384, ring(-119.7, 37.5, -119.5, 37.7))
    assert wfigs.match([fire], [scar, small])[fire.id].name == "Dome"


def test_a_small_fire_cannot_claim_a_hotspot_twelve_km_away():
    # 30 acres is ~200 m across; the LA County failure in one assertion.
    fire = incident(-118.24, 33.80)
    far = record("Lac-335519", -118.35, 33.85, 30)
    assert wfigs.match([fire], [far]) == {}


def test_a_big_fire_may_claim_a_hotspot_kilometres_out():
    fire = incident(-121.04, 48.93)
    big = record("Border 2", -121.10, 48.90, 8707)
    assert wfigs.match([fire], [big])[fire.id].name == "Border 2"


def test_reach_scales_with_size_but_stays_inside_its_bounds():
    assert wfigs._reach_km(record("x", 0, 0, None)) == wfigs.MATCH_MIN_KM
    assert wfigs._reach_km(record("x", 0, 0, 1)) == wfigs.MATCH_MIN_KM
    assert wfigs._reach_km(record("x", 0, 0, 5_000_000)) == wfigs.MATCH_MAX_KM
    assert wfigs.MATCH_MIN_KM < wfigs._reach_km(record("x", 0, 0, 8707)) < wfigs.MATCH_MAX_KM


def test_two_clusters_of_one_incident_merge_into_one_fire():
    head, flank = incident(-121.04, 48.93), incident(-120.93, 49.13)
    same = record("Border 2", -121.0, 49.0, 8707)
    official = {head.id: same, flank.id: same}

    merged, rekeyed = national.merge_by_official([head, flank], official)

    assert len(merged) == 1
    assert len(merged[0].hotspots) == 4
    assert rekeyed[merged[0].id].name == "Border 2"  # re-keyed: the centroid moved


def test_unmatched_clusters_survive_the_merge_untouched():
    known, unknown = incident(-121.04, 48.93), incident(-90.7, 35.6)
    merged, rekeyed = national.merge_by_official(
        [known, unknown], {known.id: record("Border 2", -121.0, 49.0, 8707)})
    assert {i.id for i in merged} == {known.id, unknown.id}
    assert unknown.id not in rekeyed


def test_official_fires_outrank_a_brighter_crop_burn():
    """FIRMS cannot tell a burning field from a wildfire. WFIGS can."""
    delta = incident(-90.74, 35.65, count=8)          # a very bright ag burn
    named = incident(-119.61, 37.60)
    order = national.rank([delta, named], {named.id: record("Dome", -119.6, 37.6)})
    assert [i.id for i in order] == [named.id, delta.id]


def test_a_perimeter_seeds_the_cells_it_covers():
    """The GeoJSON perimeter has to land on the EPSG:5070 grid, not near it."""
    shape_, transform = _grid_over(-119.65, 37.55, -119.55, 37.65)
    mask = spread.seed_from_perimeter(ring(-119.62, 37.58, -119.58, 37.62),
                                      transform, shape_)
    assert mask.any()
    assert not mask.all()  # part of the box, not the whole thing
    # The burned cells sit inside the grid rather than smeared to an edge,
    # which is what a dropped or doubled reprojection looks like.
    rows, cols = mask.nonzero()
    assert 0 < rows.min() and rows.max() < shape_[0] - 1
    assert 0 < cols.min() and cols.max() < shape_[1] - 1


def _grid_over(west, south, east, north, cell_m=120.0):
    """A small EPSG:5070 grid covering a lon/lat box, as gather() would build."""
    from pyproj import Transformer
    from affine import Affine

    bounds = Transformer.from_crs(
        "EPSG:4326", "EPSG:5070", always_xy=True).transform_bounds(
            west, south, east, north)
    left, bottom, right, top = bounds
    shape_ = (int((top - bottom) / cell_m), int((right - left) / cell_m))
    return shape_, Affine(cell_m, 0, left, 0, -cell_m, top)


def test_perimeter_and_detections_union_rather_than_replace():
    shape_, transform = _grid_over(-119.65, 37.55, -119.55, 37.65)
    perimeter = spread.seed_from_perimeter(
        ring(-119.63, 37.56, -119.62, 37.57), transform, shape_)
    detections = spread.seed_from_hotspots(
        [spot(-119.57, 37.64)], transform, shape_)
    both = perimeter | detections
    assert both.sum() > perimeter.sum() > 0
    assert both.sum() > detections.sum() > 0


def test_a_contained_fire_sorts_below_one_still_open():
    """Contained means a line is around it, not that it stopped burning."""
    out = incident(-121.04, 48.93)
    open_ = incident(-119.61, 37.60)
    contained = wfigs.Record(name="Hoag", irwin_id="{h}", lon=-121.0, lat=48.9,
                             acres=50224, contained_pct=100)
    burning = wfigs.Record(name="Dome", irwin_id="{d}", lon=-119.6, lat=37.6,
                           acres=2384, contained_pct=15)
    order = national.rank([out, open_], {out.id: contained, open_.id: burning})
    assert [i.id for i in order] == [open_.id, out.id]


def ago(days):
    stamp = datetime.now(timezone.utc) - timedelta(days=days)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def filed(name, contained=None, updated_days=0, **kw):
    return wfigs.Record(name=name, irwin_id="{" + name + "}", lon=-119.61,
                        lat=37.60, contained_pct=contained,
                        modified=ago(updated_days), **kw)


def test_a_fully_contained_fire_is_not_active():
    """A 50,000-acre July fire smoulders for weeks and VIIRS keeps seeing it."""
    assert not filed("Hoag", contained=100).active
    assert filed("Dome", contained=15).active


def test_a_record_nobody_has_touched_in_a_week_is_not_active():
    assert not filed("Forgotten", contained=20,
                     updated_days=wfigs.STALE_AFTER_DAYS + 1).active
    assert filed("Worked", contained=20,
                 updated_days=wfigs.STALE_AFTER_DAYS - 1).active


def test_a_fire_burning_for_months_stays_active_while_it_is_worked():
    """Border 2: reported 65 days ago, 74% contained, updated today."""
    assert filed("Border 2", contained=74, updated_days=0).active


def test_an_unknown_update_time_does_not_disqualify_a_fire():
    assert wfigs.Record(name="Perimeter Only", irwin_id="{p}", lon=0, lat=0).active


def test_currently_active_sorts_the_map_into_burning_and_not():
    burning = incident(-119.61, 37.60)
    contained = incident(-120.22, 45.64)
    forgotten = incident(-121.04, 48.93)
    flare = incident(-95.11, 29.75)
    unfiled = incident(-90.74, 35.65)
    official = {
        burning.id: filed("Dome", contained=15),
        contained.id: filed("Hoag", contained=100),
        forgotten.id: filed("Forgotten", contained=20, updated_days=30),
    }
    persistent = {(round(h.lon / national.CELL_DEG), round(h.lat / national.CELL_DEG))
                  for h in flare.hotspots}

    kept, dropped = national.currently_active(
        [burning, contained, forgotten, flare, unfiled], official, persistent)

    assert {i.id for i in kept} == {burning.id, unfiled.id}
    assert {reason for _, _, reason in dropped} == {
        "contained", "record stale", "static heat source"}


def test_a_new_fire_nobody_has_filed_yet_is_kept():
    """First hours of a real fire: fresh heat, no incident record, not persistent."""
    new = incident(-118.5, 34.2)
    kept, dropped = national.currently_active([new], {}, set())
    assert [i.id for i in kept] == [new.id] and not dropped


def test_place_reads_as_somewhere_a_person_can_picture():
    where = wfigs.Record(name="Dome", irwin_id="{d}", lon=-119.6, lat=37.6,
                         county="Mariposa", state="US-CA")
    assert where.place == "Mariposa County, CA"
    assert wfigs.Record(name="x", irwin_id="{x}", lon=0, lat=0).place is None
