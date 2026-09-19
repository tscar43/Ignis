"""Wind for the spread model. NWS for live, Open-Meteo's archive for replay.
The one thing to get right: both sources report the direction wind comes
FROM. Fire spreads TOWARD (from + 180) % 360. Every value leaving this module
is already flipped, so nothing downstream should flip it again.
Neither source needs an API key.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timezone
import httpx
NWS = "https://api.weather.gov"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
# NWS asks for a contact in the User-Agent and throttles anonymous callers.
HEADERS = {"User-Agent": "Ignis wildfire evacuation demo (github.com/tscar43/Ignis)"}
@dataclass(frozen=True)
class Wind:
    speed_kmh: float
    toward_deg: float  # already flipped from the reported "from" direction
    observed_at: str  # ISO8601 Z, for the contract's data_as_of.weather
    @property
    def compass(self) -> str:
        points = ["north", "northeast", "east", "southeast",
                  "south", "southwest", "west", "northwest"]
        return points[round(self.toward_deg / 45) % 8]
def _toward(from_deg: float) -> float:
    return (from_deg + 180) % 360
@lru_cache(maxsize=32)
def _archive_day(lat: float, lon: float, day: str) -> dict:
    """One request per day. A replay loop asks for many hours of the same day,
    and Open-Meteo drops the connection if you ask per hour."""
    return httpx.get(ARCHIVE, timeout=60, params={
        "latitude": lat, "longitude": lon, "start_date": day, "end_date": day,
        "hourly": "wind_speed_10m,wind_direction_10m", "timezone": "UTC",
    }).json()["hourly"]
def live(lat: float, lon: float) -> Wind:
    """Current NWS gridpoint wind. Two hops: /points then the gridpoint URL."""
    with httpx.Client(headers=HEADERS, timeout=60) as client:
        point = client.get(f"{NWS}/points/{lat},{lon}").json()
        grid = client.get(point["properties"]["forecastGridData"]).json()["properties"]
    speed = grid["windSpeed"]["values"][0]
    direction = grid["windDirection"]["values"][0]
    # validTime is an interval, "2026-09-19T12:00:00+00:00/PT3H"; keep the start.
    stamp = speed["validTime"].split("/")[0]
    return Wind(
        speed_kmh=round(float(speed["value"]), 1),
        toward_deg=_toward(float(direction["value"])),
        observed_at=datetime.fromisoformat(stamp).astimezone(timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
def archived(lat: float, lon: float, when: datetime, peak_window_h: int = 0) -> Wind:
    """Reanalysis wind for a past hour, for replay.
    `peak_window_h` > 0 returns the strongest hour within +/- that many hours
    instead of the exact hour. ERA5 reanalysis is ~25 km resolution, which
    smooths terrain-driven wind badly: on the Camp Fire morning it reports
    28 km/h at 12:00Z and 4 km/h at 19:00Z, while the RAWS stations in Jarbo
    Gap were recording gusts several times that. The exact hour will
    under-drive the model; the window is the honest workaround.
    """
    hourly = _archive_day(lat, lon, when.astimezone(timezone.utc).date().isoformat())
    target = when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    index = hourly["time"].index(target.strftime("%Y-%m-%dT%H:%M"))
    if peak_window_h:
        lo = max(0, index - peak_window_h)
        hi = min(len(hourly["time"]), index + peak_window_h + 1)
        speeds = hourly["wind_speed_10m"][lo:hi]
        index = lo + speeds.index(max(speeds))
    return Wind(
        speed_kmh=round(hourly["wind_speed_10m"][index], 1),
        toward_deg=_toward(hourly["wind_direction_10m"][index]),
        observed_at=hourly["time"][index] + ":00Z",
    )
if __name__ == "__main__":
    here = (39.76, -121.62)
    print("live:", live(*here))
    camp = datetime(2018, 11, 8, 19, 50, tzinfo=timezone.utc)
    print("replay, exact hour:", archived(*here, camp))
    print("replay, peak +/-8h:", archived(*here, camp, peak_window_h=8))
    print("\nhourly profile, Camp Fire day:")
    for hour in range(0, 24, 2):
        w = archived(*here, camp.replace(hour=hour))
        print(f"  {w.observed_at}  {w.speed_kmh:>5} km/h toward {w.toward_deg:>5.0f} "
              f"({w.compass})")
