"""Offline tests for the wind module. No network.

Both sources report the direction wind comes FROM; everything leaving `nws.py`
is already flipped to TOWARD. A second flip downstream runs the fire backwards
and still looks plausible on a map, so the convention gets a test at the source
as well as in `test_spread.py`. The two parsing traps in the module's comments
-- the `validTime` interval and the peak-window index -- are covered here too.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.weather import nws  # noqa: E402

# One Open-Meteo day as `_archive_day` returns it. Calm and from the northeast
# all day, except a 40 km/h peak at 12:00Z blowing from due south. Stamped with
# the day it was asked for, because `_archive_span` concatenates two of these
# and a fixture that ignores the date would hide which day an hour came from.
def _day(day: str, peak_hour: int | None = 12) -> dict:
    return {
        "time": [f"{day}T{h:02d}:00" for h in range(24)],
        "wind_speed_10m": [40.0 if h == peak_hour else 5.0 for h in range(24)],
        "wind_direction_10m": [180.0 if h == peak_hour else 45.0 for h in range(24)],
    }


HOURLY = _day("2018-11-08")

CAMP = datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)


@pytest.fixture
def archive(monkeypatch):
    # Only the 8th is windy; the 7th is calm throughout, so a window that
    # reaches back across midnight is visible in the result.
    monkeypatch.setattr(nws, "_archive_day", lambda lat, lon, day: _day(
        day, peak_hour=12 if day == "2018-11-08" else None))


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


def test_peak_window_near_midnight_reaches_into_the_previous_day(archive):
    """02:00 - 8 h is 18:00 the day before, not 18:00 the same day.

    Two bugs met here. A negative index sliced from the far end of the day and
    read the wrong hours; clamping that at 0 then silently shortened the window
    to whatever fitted inside one UTC date. The replay runs past midnight, so
    the window has to span the request, and `_archive_span` fetches the day
    before to make that possible.
    """
    wind = nws.archived(39.76, -121.62, CAMP.replace(hour=2), peak_window_h=8)
    assert wind.speed_kmh == 5.0  # the 7th is calm all day
    assert wind.observed_at.startswith("2018-11-07T18:00")


def test_peak_window_is_causal_by_default(archive):
    """A replay must not be driven by wind from after the moment it replays.

    At 06:00Z the 12:00Z peak has not happened yet. The symmetric window used
    to reach it anyway, which turned "what we would have said at 06:00" into a
    retrospective best case.
    """
    at_six = CAMP.replace(hour=6, minute=0)
    assert nws.archived(39.76, -121.62, at_six, peak_window_h=8).speed_kmh == 5.0
    retrospective = nws.archived(39.76, -121.62, at_six, peak_window_h=8,
                                 causal=False)
    assert retrospective.speed_kmh == 40.0
    assert retrospective.observed_at == "2018-11-08T12:00:00Z"


def _fake_grid(monkeypatch, grid):
    point = {"properties": {"forecastGridData": "https://api.weather.gov/gridpoints/x"}}

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def get(self, url):
            return SimpleNamespace(json=lambda: point if "/points/" in url else grid)

    monkeypatch.setattr(nws.httpx, "Client", lambda **kw: FakeClient())


def _current(hours_ago=1.0, duration="PT3H", offset_hours=-8):
    """A validTime interval that covers now, written in a non-UTC offset.

    NWS serves local offsets, and `observed_at` has to come back in UTC.
    Anchored on the real clock because `_covering` checks both ends of the
    interval now -- a fixed 2018 timestamp is an expired forecast, which is
    exactly what it is supposed to reject.
    """
    zone = timezone(timedelta(hours=offset_hours))
    start = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)
             ).replace(microsecond=0).astimezone(zone)
    return f"{start.isoformat()}/{duration}", start.astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_gridpoint_keeps_the_start_of_the_validTime_interval(monkeypatch):
    valid, expected = _current()
    _fake_grid(monkeypatch, {"properties": {
        "windSpeed": {"values": [{"validTime": valid, "value": 35.04}]},
        "windDirection": {"values": [{"validTime": valid, "value": 45.0}]},
    }})
    wind = nws.nws_gridpoint(39.76, -121.62)
    assert wind.observed_at == expected
    assert wind.speed_kmh == 35.0
    assert wind.toward_deg == 225


def test_gridpoint_reads_the_hour_covering_now_not_the_first_in_the_series(monkeypatch):
    """values[0] is the start of the issuance, not the current hour.

    A live run read 13:00Z wind at 20:03Z this way and shipped it as
    data_as_of.weather. Speed and direction break at different times, so each
    series has to be selected on its own -- taking index 0 of both was one bug
    that looked like two.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def span(hours_ago, value, duration="PT1H"):
        stamp = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        return {"validTime": f"{stamp}/{duration}", "value": value}

    # Only the middle entry of each series is still valid: the first expired
    # hours ago, the last has not started.
    _fake_grid(monkeypatch, {"properties": {
        "windSpeed": {"values": [span(7, 5.0), span(1, 40.0, "PT3H"),
                                 span(-3, 99.0)]},
        "windDirection": {"values": [span(9, 0.0), span(2, 45.0, "PT4H"),
                                     span(-5, 270.0)]},
    }})
    wind = nws.nws_gridpoint(39.76, -121.62)
    assert wind.speed_kmh == 40.0    # not 5.0, the stale first entry
    assert wind.toward_deg == 225    # from 45, and off its own breakpoint
    assert wind.observed_at == (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_gridpoint_refuses_a_series_that_does_not_cover_now(monkeypatch):
    """No valid forecast is an error, not a reason to serve the nearest one.

    The old fallback returned `values[0]` whenever nothing covered now, so a
    single expired entry -- one hour of it, from 2020 -- came back as the
    current wind and went into the payload as `data_as_of.weather`.
    """
    ahead = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00")
    _fake_grid(monkeypatch, {"properties": {
        "windSpeed": {"values": [{"validTime": f"{ahead}/PT1H", "value": 12.0}]},
        "windDirection": {"values": [{"validTime": f"{ahead}/PT1H", "value": 180.0}]},
    }})
    with pytest.raises(RuntimeError, match="no entry valid now"):
        nws.nws_gridpoint(39.76, -121.62)


def test_gridpoint_refuses_an_expired_interval(monkeypatch):
    _fake_grid(monkeypatch, {"properties": {
        "windSpeed": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/PT1H",
                                  "value": 12.0}]},
        "windDirection": {"values": [{"validTime": "2020-01-01T00:00:00+00:00/PT1H",
                                      "value": 180.0}]},
    }})
    with pytest.raises(RuntimeError, match="no entry valid now"):
        nws.nws_gridpoint(39.76, -121.62)


def test_validTime_durations_carry_days_as_well_as_hours():
    start, end = nws._interval("2026-09-19T12:00:00+00:00/P1DT2H")
    assert (end - start) == timedelta(days=1, hours=2)


def test_hrrr_flips_to_toward_and_stamps_the_hour(monkeypatch):
    monkeypatch.setattr(nws.httpx, "get", lambda *a, **kw: SimpleNamespace(
        json=lambda: {"current": {"time": "2026-09-19T20:00",
                                  "wind_speed_10m": 11.23,
                                  "wind_direction_10m": 266.0}}))
    wind = nws.hrrr(37.62, -119.60)
    assert wind.speed_kmh == 11.2
    assert wind.toward_deg == 86  # from 266, so toward 86
    assert wind.observed_at == "2026-09-19T20:00:00Z"


def test_live_falls_back_to_the_gridpoint_when_hrrr_is_unreachable(monkeypatch):
    def boom(*a, **kw):
        raise nws.httpx.ConnectError("open-meteo down")

    monkeypatch.setattr(nws.httpx, "get", boom)
    valid, _ = _current()
    _fake_grid(monkeypatch, {"properties": {
        "windSpeed": {"values": [{"validTime": valid, "value": 35.04}]},
        "windDirection": {"values": [{"validTime": valid, "value": 45.0}]},
    }})
    assert nws.live(39.76, -121.62).speed_kmh == 35.0
