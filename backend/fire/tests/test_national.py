"""Offline tests for national discovery. No network.

The failure mode worth pinning is clustering: too eager and two fires in the
same county become one incident whose bbox spans both and whose polygons join
them; too shy and one fire's VIIRS and NOAA-20 pixels model as two fires and
the map shows a duplicate. Both look plausible on a map.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import national  # noqa: E402
from backend.fire.firms import Hotspot  # noqa: E402

ACQ = datetime(2026, 9, 19, 20, 1, 17, tzinfo=timezone.utc)


def spot(lon, lat, frp=10.0, minutes=0, sensor="VIIRS/N20"):
    return Hotspot(lon=lon, lat=lat, confidence="h", frp=frp,
                   acq_time=ACQ + timedelta(minutes=minutes), sensor=sensor,
                   source="VIIRS_NOAA20_NRT")


def test_two_sensors_on_one_fire_are_one_incident():
    # Same fire seen 375 m apart by two instruments on different passes.
    fire = [spot(-120.500, 39.500), spot(-120.503, 39.503, minutes=40,
                                         sensor="VIIRS/SNPP")]
    assert len(national.cluster(fire)) == 1


def test_fires_ten_km_apart_stay_separate():
    both = [spot(-120.50, 39.50), spot(-120.51, 39.51),
            spot(-120.30, 39.50), spot(-120.31, 39.51)]
    assert len(national.cluster(both)) == 2


def test_chain_of_detections_joins_across_cells():
    # A fire longer than one grid cell: the flood fill has to walk it.
    run = [spot(-120.50 + 0.04 * i, 39.50) for i in range(6)]
    assert len(national.cluster(run)) == 1
    assert len(national.cluster(run)[0].hotspots) == 6


def test_lone_pixel_is_dropped_but_a_pair_is_kept():
    spots = [spot(-100.0, 35.0), spot(-120.50, 39.50), spot(-120.51, 39.50)]
    incidents = national.cluster(spots)
    assert len(incidents) == 1
    assert incidents[0].lon < -120


def test_incidents_rank_by_radiative_power():
    spots = [spot(-120.50, 39.50, frp=5), spot(-120.51, 39.50, frp=5),
             spot(-118.00, 37.00, frp=400), spot(-118.01, 37.00, frp=400)]
    assert [i.frp_mw for i in national.cluster(spots)] == [800.0, 10.0]


def test_bbox_pads_the_footprint_and_keeps_lon_lat_order():
    incident = national.cluster([spot(-120.50, 39.50), spot(-120.48, 39.52)])[0]
    west, south, east, north = incident.bbox
    assert west < 0 < south  # (W, S, E, N), not the (S, W, N, E) some APIs want
    assert (west, south) == (-120.56, 39.44)
    assert (east, north) == (-120.42, 39.58)


def test_huge_complex_is_clipped_to_the_span_cap():
    # Two degrees of detections: modelling it whole is a 10M-cell Dijkstra.
    wide = [spot(-120.0 + 0.04 * i, 39.5) for i in range(50)]
    west, south, east, north = national.cluster(wide)[0].bbox
    assert round(east - west, 4) == national.MAX_SPAN_DEG
    assert north - south < national.MAX_SPAN_DEG  # only the wide axis is clipped


def test_seed_time_is_the_newest_pass():
    incident = national.cluster([spot(-120.50, 39.50),
                                 spot(-120.51, 39.50, minutes=90)])[0]
    assert incident.seed_time == ACQ + timedelta(minutes=90)


def test_id_is_stable_under_a_pixel_of_growth():
    first = national.cluster([spot(-120.500, 39.500), spot(-120.501, 39.500)])[0]
    grown = national.cluster([spot(-120.500, 39.500), spot(-120.501, 39.500),
                              spot(-120.502, 39.501)])[0]
    assert first.id == grown.id == "39.50N120.50W"


def test_one_failing_fire_does_not_take_down_the_run():
    def boom(_):
        raise RuntimeError("LANDFIRE 503")

    payload, error = national._safe(boom)(object())
    assert payload is None and error == "RuntimeError: LANDFIRE 503"
