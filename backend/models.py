"""Pydantic contracts for the Wildfire Evacuation Intelligence backend.

Two contracts live here:
  * FireRisk*  - input consumed from the Geospatial service (EPSG:4326 GeoJSON)
  * Route* / PlanResponse - output produced for the Frontend (minutes + km)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# GeoJSON (minimal, EPSG:4326)
# ---------------------------------------------------------------------------
class GeoJSONGeometry(BaseModel):
    type: str
    coordinates: Any


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"]
    properties: dict[str, Any] = Field(default_factory=dict)
    geometry: GeoJSONGeometry


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[GeoJSONFeature] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fire risk input (from Geospatial, demo_data/fire.json)
# ---------------------------------------------------------------------------
class DataAsOf(BaseModel):
    firms: str
    weather: str


RiskBand = Literal["current", "h1", "h3", "h6"]


class RiskPolygons(BaseModel):
    """Cumulative bands: h6 >= h3 >= h1 >= current."""

    current: GeoJSONFeatureCollection
    h1: GeoJSONFeatureCollection
    h3: GeoJSONFeatureCollection
    h6: GeoJSONFeatureCollection


class FireRiskInput(BaseModel):
    generated_at: str
    data_as_of: DataAsOf
    fire_points: GeoJSONFeatureCollection
    risk_polygons: RiskPolygons
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shelters
# ---------------------------------------------------------------------------
class Shelter(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    accepts_pets: bool
    accessible: bool
    capacity: int


# ---------------------------------------------------------------------------
# Route output (to Frontend; units: minutes and kilometers, EPSG:4326)
# ---------------------------------------------------------------------------
class Origin(BaseModel):
    lat: float
    lon: float
    label: str = ""


class Destination(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    accepts_pets: bool
    accessible: bool


class RouteGeometry(BaseModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = Field(default_factory=list)


RouteType = Literal["recommended", "fastest", "alternative"]


class ExposureBreakdownKm(BaseModel):
    """Kilometres of route inside each cumulative band."""

    current: float = 0.0
    h1: float = 0.0
    h3: float = 0.0
    h6: float = 0.0


class Route(BaseModel):
    type: RouteType
    geometry: RouteGeometry
    travel_time_min: float
    distance_km: float
    exposure: float = Field(ge=0.0, le=1.0, description="Weighted exposure, 0-1")
    exposure_breakdown_km: ExposureBreakdownKm = Field(
        default_factory=ExposureBreakdownKm
    )
    named_roads: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    generated_at: str
    data_as_of: DataAsOf
    origin: Origin
    destination: Destination
    routes: list[Route]
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------
class GeocodeRequest(BaseModel):
    address: str
    lat: float | None = Field(default=None, description="Fallback coordinate")
    lon: float | None = Field(default=None, description="Fallback coordinate")


class GeocodeResponse(BaseModel):
    address: str
    lat: float
    lon: float
    source: Literal["demo", "echo"]


# ---------------------------------------------------------------------------
# Plan request ({origin, household, t} -> PlanResponse)
# ---------------------------------------------------------------------------
class Household(BaseModel):
    occupants: int = 1
    has_vehicle: bool = True
    accepts_pets: bool = False
    wheelchair_accessible: bool = False


class PlanRequest(BaseModel):
    origin: Origin
    household: Household = Field(default_factory=Household)
    t: str | None = Field(
        default=None, description="Replay time offset, e.g. 'T0' | 'H1' | 'H3' | 'H6'"
    )


# ---------------------------------------------------------------------------
# Chat (agent loop hosted server-side, key stays here)
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
