"""Offline tests for FIRMS parsing. No network: these guard the contract's
`fire_points` shape and the two parsing traps in real FIRMS CSV.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.fire import firms  # noqa: E402

VIIRS_ROW = {
    "latitude": "39.69794", "longitude": "-121.63232", "acq_date": "2018-11-08",
    "acq_time": "1950", "satellite": "N", "instrument": "VIIRS",
    "confidence": "n", "frp": "11.55", "type": "0",
}


def test_parses_a_viirs_row_into_lon_lat_order():
    hotspot = firms._parse_row(VIIRS_ROW, "VIIRS_SNPP_SP")
    assert (hotspot.lon, hotspot.lat) == (-121.63232, 39.69794)
    assert hotspot.acq_time == datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)
    assert hotspot.frp == 11.55


def test_acq_time_without_leading_zero_is_not_read_as_afternoon():
    """FIRMS writes 00:50 UTC as "50". Naive parsing turns it into 05:00."""
    hotspot = firms._parse_row({**VIIRS_ROW, "acq_time": "50"}, "VIIRS_SNPP_SP")
    assert hotspot.acq_time.hour == 0
    assert hotspot.acq_time.minute == 50


@pytest.mark.parametrize(
    "raw,expected",
    [("l", "l"), ("n", "n"), ("h", "h"),  # VIIRS
     ("12", "l"), ("50", "n"), ("87", "h"),  # MODIS percentages
     ("", "n")],  # missing -> nominal rather than a crash
)
def test_confidence_normalizes_across_sensors(raw, expected):
    assert firms._normalize_confidence(raw) == expected


def test_feature_matches_the_contract():
    feature = firms._parse_row(VIIRS_ROW, "VIIRS_SNPP_SP").as_feature()
    assert feature["geometry"]["type"] == "Point"
    lon, lat = feature["geometry"]["coordinates"]
    assert -180 <= lon <= 180 and -90 <= lat <= 90
    assert lon < 0 < lat, "coordinates must be [lon, lat], not [lat, lon]"
    assert set(feature["properties"]) >= {"confidence", "frp", "acq_time"}
    assert feature["properties"]["acq_time"].endswith("Z")


def test_latest_acq_time_reports_the_newest_observation():
    rows = [firms._parse_row({**VIIRS_ROW, "acq_time": t}, "X")
            for t in ("1950", "0050", "2130")]
    assert firms.latest_acq_time(rows) == "2018-11-08T21:30:00Z"
    assert firms.latest_acq_time([]) is None


def test_rejects_a_flipped_bbox_before_spending_a_request():
    with pytest.raises(ValueError, match="west, south, east, north"):
        firms.fetch_hotspots(bbox=(-121.4, 39.95, -121.8, 39.6))


def test_rejects_a_day_range_the_api_will_not_serve():
    with pytest.raises(ValueError, match="API limit"):
        firms.fetch_hotspots(days=firms.MAX_DAY_RANGE + 1)
