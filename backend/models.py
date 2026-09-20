from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ReplayTime = Literal['T0', 'H1', 'H3', 'H6']


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Origin(Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = ''


class Household(Model):
    occupants: int = Field(default=1, ge=1, le=100)
    has_vehicle: bool = True
    accepts_pets: bool = False
    wheelchair_accessible: bool = False
    # Asthma, COPD, pregnancy, infants. Prefers routes out of the modelled
    # downwind plume; never permits one an evacuation order forbids.
    respiratory_sensitive: bool = False


class PlanRequest(Model):
    origin: Origin
    household: Household = Field(default_factory=Household)
    t: ReplayTime = 'T0'
    mode: Literal['demo', 'replay', 'live'] = 'demo'
    shelter_source: Literal['demo', 'fema'] = 'demo'


class ShelterEntrance(Origin):
    source_url: str = Field(min_length=1)
    verified_at: AwareDatetime


class Shelter(Origin):
    id: str
    name: str
    accepts_pets: bool | None = None
    accessible: bool | None = None
    capacity: int | None = Field(default=None, ge=0)
    source: Literal['demo', 'fema'] = 'demo'
    status: Literal['DEMO', 'OPEN', 'CLOSED', 'FULL', 'ALERT', 'STANDBY', 'UNKNOWN'] = 'DEMO'
    source_url: str | None = None
    fetched_at: AwareDatetime | None = None
    address: str = ''
    reported_population: int | None = Field(default=None, ge=0)
    pet_policy: str | None = None
    entrance: ShelterEntrance | None = None


class DataAsOf(Model):
    firms: str
    weather: str


class RouteGeometry(Model):
    type: Literal['LineString'] = 'LineString'
    coordinates: list[tuple[float, float]] = Field(min_length=2)


class ExposureBreakdown(Model):
    current: float = Field(default=0, ge=0)
    h1: float = Field(default=0, ge=0)
    h3: float = Field(default=0, ge=0)
    h6: float = Field(default=0, ge=0)
    # Kilometres inside the modelled downwind plume. Overlaps the bands above
    # rather than partitioning with them, so do not sum the five.
    smoke: float = Field(default=0, ge=0)


class Route(Model):
    type: Literal['recommended', 'alternative', 'comparison']
    geometry: RouteGeometry
    travel_time_min: float = Field(ge=0)
    distance_km: float = Field(ge=0)
    exposure: float = Field(ge=0, le=1)
    exposure_breakdown_km: ExposureBreakdown
    named_roads: list[str]


class PlanResponse(Model):
    generated_at: str
    data_as_of: DataAsOf
    origin: Origin
    destination: Shelter
    routes: list[Route]
    warnings: list[str]
    evacuation: dict = Field(default_factory=dict)


class GeocodeRequest(Model):
    address: str = Field(min_length=1, max_length=300)


class ChatRequest(Model):
    messages: list[dict[str, str]] = Field(max_length=100)
