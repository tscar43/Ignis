"""Wildfire Evacuation Intelligence Agent - FastAPI backend.

Milestone 1: app skeleton, CORS, health, demo fire/shelter serving, geocode,
and explicit 501 stubs for the endpoints filled in by later milestones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (
    ChatRequest,
    FireRiskInput,
    GeocodeRequest,
    GeocodeResponse,
    PlanRequest,
    Shelter,
)

SERVICE_NAME = "wildfire-evacuation-intelligence"
DEMO_DATA_DIR = Path(__file__).resolve().parent.parent / "demo_data"

app = FastAPI(
    title="Wildfire Evacuation Intelligence Agent",
    description="Routes and fire-risk API for the Ignis demo. Units: minutes, km, EPSG:4326.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _not_implemented(what: str, milestone: str) -> JSONResponse:
    detail = f"{what} is not implemented yet (planned for {milestone})."
    return JSONResponse(status_code=501, content={"detail": detail})


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/fire", response_model=FireRiskInput)
def fire(
    lat: float = Query(..., description="Latitude of area of interest (EPSG:4326)"),
    lon: float = Query(..., description="Longitude of area of interest (EPSG:4326)"),
    t: str | None = Query(default=None, description="Replay time offset, e.g. T0/H1/H3/H6"),
) -> dict[str, Any]:
    """Serve the fire-risk GeoJSON for the area. Currently the demo scenario."""
    data = _load_json(DEMO_DATA_DIR / "fire.json")
    FireRiskInput.model_validate(data)
    return data


@app.get("/shelters", response_model=list[Shelter])
def shelters() -> list[dict[str, Any]]:
    """All demo shelters for the map."""
    data = _load_json(DEMO_DATA_DIR / "shelters.json")
    return data


DEMO_ADDRESSES: dict[str, tuple[float, float]] = {
    "123 oak st": (39.76, -121.62),
    "456 canyon dr": (39.752, -121.655),
    "1200 highland way": (39.796, -121.662),
    "1400 ridge rd": (39.801, -121.698),
    "1000 fair oaks blvd": (39.77, -121.668),
}


def _normalize(address: str) -> str:
    lowered = address.lower()
    for ch in (",", ".", "#", "!"):
        lowered = lowered.replace(ch, " ")
    return " ".join(lowered.split())


@app.post("/geocode", response_model=GeocodeResponse)
def geocode(req: GeocodeRequest) -> GeocodeResponse:
    """Address -> coordinates. Hardcoded demo matches, else echo provided coords."""
    needle = _normalize(req.address)
    for key, (lat, lon) in DEMO_ADDRESSES.items():
        if key in needle:
            return GeocodeResponse(
                address=req.address, lat=lat, lon=lon, source="demo"
            )
    if req.lat is not None and req.lon is not None:
        return GeocodeResponse(
            address=req.address, lat=req.lat, lon=req.lon, source="echo"
        )
    raise HTTPException(
        status_code=404,
        detail=f"Address '{req.address}' not in demo data and no fallback coordinates given.",
    )


@app.post("/plan")
def plan(req: PlanRequest) -> JSONResponse:
    return _not_implemented("POST /plan (route computation)", "Milestone 2-5")


@app.get("/scenario/{t}")
def scenario(t: str) -> JSONResponse:
    return _not_implemented(f"GET /scenario/{t} (replay snapshots)", "Milestone 7")


@app.post("/chat")
def chat(req: ChatRequest) -> JSONResponse:
    return _not_implemented("POST /chat (agent endpoint)", "Milestone 8")
