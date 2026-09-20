import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.evacuations import EvacuationsUnavailable, read_evacuations, origin_orders
from .api.palisades_demo import (DemoUnavailable, PalisadesDemoRequest, PalisadesPlanResponse,
                                  ROUTING, demo_info, plan_demo)
from .api.fire_service import FireUnavailable, get_fire_result
from .models import (ChatRequest, GeocodeRequest, Household, Origin,
                     PlanRequest, PlanResponse, ReplayTime, Shelter)
from .routing.routes import calculate_routes
from .shelters.shelters import find_shelters
from .shelters.fema import ShelterUnavailable, access_report, read_catalogue
from .routing.roads import RoadUnavailable, load_graph, read_graph

app = FastAPI(title='Ignis API', version='0.3.0')
app.add_middleware(CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get(
        'IGNIS_CORS_ORIGINS', 'http://localhost:5173,http://localhost:3000').split(',')
        if origin.strip()],
    allow_methods=['GET', 'POST'], allow_headers=['*'],
    expose_headers=['X-Fire-Source', 'X-Fire-Stale', 'X-Fire-Cache-Age'])


@app.exception_handler(RoadUnavailable)
@app.exception_handler(DemoUnavailable)
async def unavailable_dataset(request, exc):
    return JSONResponse(status_code=503, content={'detail': str(exc)})


@app.get('/ready')
def ready():
    """Validate bundled demo inputs without calling live upstream services."""
    try:
        get_fire_result('demo', 'T0')
        load_graph()
        find_shelters()
        demo_info()
        read_graph(ROUTING / 'osm/palisades.graphml')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, 'Demo data missing or invalid') from exc
    return {'status': 'ready', 'scope': 'offline_demos'}


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'wildfire-evacuation-intelligence'}


def fire_for_time(mode, t, response):
    try:
        result = get_fire_result(mode, t)
    except FireUnavailable as exc:
        raise HTTPException(503, str(exc), headers={'Retry-After': '30'}) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers['X-Fire-Source'] = result.source
    response.headers['X-Fire-Stale'] = str(result.stale).lower()
    response.headers['X-Fire-Cache-Age'] = str(result.age_seconds)
    response.headers['Cache-Control'] = 'no-store'
    return result.payload


@app.get('/fire', response_model=None)
def fire(response: Response, mode: Literal['demo', 'replay', 'live'] = 'demo',
         t: ReplayTime = 'T0'):
    """Fixed engine area; mode explicitly selects demo, historical replay, or live."""
    return fire_for_time(mode, t, response)


@app.get('/shelters', response_model=list[Shelter])
def shelters(accepts_pets: bool = False, wheelchair_accessible: bool = False,
             occupants: int = Query(default=1, ge=1, le=100),
             source: Literal['demo', 'fema'] = 'demo'):
    try:
        return find_shelters(Household(accepts_pets=accepts_pets,
            wheelchair_accessible=wheelchair_accessible, occupants=occupants), source=source)
    except ShelterUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/shelters/catalog')
def shelter_catalog():
    try:
        data = read_catalogue()
    except ShelterUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    graph = load_graph()
    data['access'] = {s.id: access_report(s, graph) for s in data['shelters']}
    return data


@app.post('/geocode', response_model=Origin)
def geocode(request: GeocodeRequest):
    address = ' '.join(request.address.lower().replace('.', '').split())
    if address not in ('123 oak st', '123 oak street'):
        raise HTTPException(404, 'Unknown demo address. Use 123 Oak St or submit coordinates to /plan.')
    return Origin(lat=39.76, lon=-121.62, label=request.address)


@app.post('/plan', response_model=PlanResponse)
def plan(request: PlanRequest, response: Response):
    payload = fire_for_time(request.mode, request.t, response)
    if request.mode == 'live' and response.headers.get('X-Fire-Stale') == 'true':
        raise HTTPException(503, 'Live routing requires fresh fire data')
    try:
        return calculate_routes(request, payload)
    except (ShelterUnavailable, EvacuationsUnavailable) as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/scenario/{t}', response_model=None)
def scenario(t: ReplayTime, response: Response):
    """Return an existing fire replay frame unchanged (does not include routes)."""
    return fire_for_time('replay', t, response)


@app.post('/chat')
def chat(request: ChatRequest):
    raise HTTPException(501, 'Frontend agent integration is not installed yet')


@app.get('/evacuations')
def evacuations(response: Response, mode: Literal['demo', 'replay', 'live'] = 'live',
                lat: float | None = Query(default=None, ge=-90, le=90),
                lon: float | None = Query(default=None, ge=-180, le=180)):
    if (lat is None) != (lon is None):
        raise HTTPException(422, 'Provide both lat and lon, or neither')
    response.headers['Cache-Control'] = 'no-store'
    try:
        data = read_evacuations(mode)
        return origin_orders(data, lon, lat) if lat is not None else data
    except EvacuationsUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/demo/palisades')
def palisades_info(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return demo_info()
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Palisades demo assets unavailable') from exc


@app.post('/demo/palisades/plan', response_model=PalisadesPlanResponse)
def palisades_plan(request: PalisadesDemoRequest, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Fire-Source'] = 'palisades-historical'
    try:
        return plan_demo(request)
    except OSError as exc:
        raise HTTPException(503, 'Palisades demo assets unavailable') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
