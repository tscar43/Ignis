"""Offline tests for the wind module. No network.

Both sources report the direction wind comes FROM; everything leaving `nws.py`
is already flipped to TOWARD. A second flip downstream runs the fire backwards
and still looks plausible on a map, so the convention gets a test at the source
as well as in `test_spread.py`. The two parsing traps in the module's comments
-- the `validTime` interval and the peak-window index -- are covered here too.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.weather import nws  # noqa: E402

# One Open-Meteo day as `_archive_day` returns it. Calm and from the northeast
# all day, except a 40 km/h peak at 12:00Z blowing from due south.
HOURLY = {
    "time": [f"2018-11-08T{h:02d}:00" for h in range(24)],
    "wind_speed_10m": [40.0 if h == 12 else 5.0 for h in range(24)],
    "wind_direction_10m": [180.0 if h == 12 else 45.0 for h in range(24)],
}

CAMP = datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)


@pytest.fixture
def archive(monkeypatch):
    monkeypatch.setattr(nws, "_archive_day", lambda lat, lon, day: HOURLY)


def test_wind_from_the_northeast_spreads_to_the_southwest():
    assert nws._toward(45) == 225
    assert nws.Wind(5.0, 225, "").compass == "southwest"


def test_compass_wraps_instead_of_running_off_the_end():
    assert nws.Wind(5.0, 350, "").compass == "north"


def test_archived_reports_toward_not_from(archive):
    assert nws.archived(39.76, -121.62, CAMP).toward_deg == 225
    assert nws.archived(39.76, -121.62, CAMP).observed_at == "2018-11-08T19:00:00Z"


def test_peak_window_picks_the_windiest_hour_and_its_own_direction(archive):
    wind = nws.archived(39.76, -121.62, CAMP, peak_window_h=8)
    assert wind.speed_kmh == 40.0
    assert wind.toward_deg == 0  # from 180 (south), so toward north
    assert wind.observed_at == "2018-11-08T12:00:00Z"


def test_peak_window_does_not_reach_past_its_own_edge(archive):
    # 19:00 +/- 6 h stops at 13:00, one hour short of the peak.
    wind = nws.archived(39.76, -121.62, CAMP, peak_window_h=6)
    assert wind.speed_kmh == 5.0


def test_peak_window_near_midnight_does_not_wrap_to_the_end_of_the_day(archive):
    # 02:00 - 8 h is a negative index, which slices from the far end of the day
    # and reads the wrong hours. The replay runs past midnight UTC, so this is
    # a live path, not a hypothetical.
    wind = nws.archived(39.76, -121.62, CAMP.replace(hour=2), peak_window_h=8)
    assert wind.speed_kmh == 5.0
    assert wind.observed_at.startswith("2018-11-08T")


def test_live_keeps_the_start_of_the_validTime_interval(monkeypatch):
    grid = {"properties": {
        # A non-UTC offset, which is how NWS actually serves these.
        "windSpeed": {"values": [{"validTime": "2018-11-08T11:50:00-08:00/PT1H",
                                  "value": 35.04}]},
        "windDirection": {"values": [{"validTime": "2018-11-08T11:50:00-08:00/PT1H",
                                      "value": 45.0}]},
    }}
    point = {"properties": {"forecastGridData": "https://api.weather.gov/gridpoints/x"}}

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def get(self, url):
            return SimpleNamespace(json=lambda: point if "/points/" in url else grid)

    monkeypatch.setattr(nws.httpx, "Client", lambda **kw: FakeClient())
    wind = nws.live(39.76, -121.62)
    assert wind.observed_at == "2018-11-08T19:50:00Z"
    assert wind.speed_kmh == 35.0
    assert wind.toward_deg == 225
